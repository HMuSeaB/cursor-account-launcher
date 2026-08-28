#!/usr/bin/env node
/**
 * Cursor Connect 窗口改写（可还原）
 *
 * 对话快照 ConversationTokenDetails.max_tokens、AvailableModels 里 grok-4.6 的
 * context_token_limit / context_token_limit_for_max_mode，以及 GetEffectiveTokenLimit。
 *
 * Connect 解包认 flags 0–3：先解压再改；回包装明文、保留 END_STREAM。
 * Agent 流按完整 Connect 帧改写（请求 + 响应），不在压缩字节上盲替 varint。
 * 包内出现 grok-4.6 / Extra High 时，除 256000 外还会把 Auto 残留的 200000/204800 等
 * 窗口字段改成 500000，这样中途从 Auto 切到 Grok 也能抬上限。
 *
 *   node patch-ctxwin.mjs apply
 *   node patch-ctxwin.mjs restore
 *   node patch-ctxwin.mjs status
 *   node patch-ctxwin.mjs selftest
 *
 * 改完请重启 Cursor。环境变量 CTXWIN_FROM / CTXWIN_TO 可改默认 256000 / 500000。
 */
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

const FROM = Number(process.env.CTXWIN_FROM || 256000);
const TO = Number(process.env.CTXWIN_TO || 500000);
const MARK_START = "/* __CTXWIN_PATCH_START__ */";
const MARK_END = "/* __CTXWIN_PATCH_END__ */";
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const STATE_PATH = path.join(SCRIPT_DIR, "ctxwin-state.json");
const BACKUP_DIR = path.join(SCRIPT_DIR, "ctxwin-backups");

function ctxwinInstall(G, FROM, TO) {
  if (!G || G.__CTXWIN_INSTALLED__) return G && G.__CTXWIN__;
  var zlibMod;
  var http2Mod;
  var httpsMod;
  try {
    zlibMod = process.getBuiltinModule("node:zlib");
    http2Mod = process.getBuiltinModule("node:http2");
    httpsMod = process.getBuiltinModule("node:https");
  } catch (_) {}
  if (!zlibMod) return;

  var FLAG_COMPRESSED = 1;
  var FLAG_END_STREAM = 2;
  var MARK = "__ctxwin";
  var logPath = "";
  try {
    var pathMod = process.getBuiltinModule("node:path");
    var osMod = process.getBuiltinModule("node:os");
    logPath = pathMod.join(osMod.tmpdir(), "cursor-ctxwin.log");
  } catch (_) {}

  function log(line) {
    if (!logPath) return;
    try {
      var fsMod = process.getBuiltinModule("node:fs");
      var s = new Date().toISOString() + " " + line + "\n";
      fsMod.appendFileSync(logPath, s);
    } catch (_) {}
  }

  function readVarint(buf, i) {
    var n = 0;
    var shift = 0;
    var b;
    do {
      if (i >= buf.length) throw new Error("truncated varint");
      b = buf[i++];
      n += (b & 0x7f) * Math.pow(2, shift);
      shift += 7;
    } while (b & 0x80);
    return [n, i];
  }

  function writeVarint(n) {
    n = n >>> 0;
    var out = [];
    while (n > 0x7f) {
      out.push((n & 0x7f) | 0x80);
      n >>>= 7;
    }
    out.push(n);
    return Buffer.from(out);
  }

  function replaceBuf(buf, a, b) {
    if (!a.length || a.length !== b.length) return buf;
    var idx = buf.indexOf(a);
    if (idx < 0) return buf;
    var copy = Buffer.from(buf);
    while (idx >= 0) {
      b.copy(copy, idx);
      idx = copy.indexOf(a, idx + b.length);
    }
    return copy;
  }

  function walkFields(buf, onField) {
    var parts = [];
    var i = 0;
    while (i < buf.length) {
      var fieldStart = i;
      var tagPair;
      try {
        tagPair = readVarint(buf, i);
      } catch (_) {
        parts.push(buf.subarray(fieldStart));
        break;
      }
      var tag = tagPair[0];
      i = tagPair[1];
      var field = tag >>> 3;
      var wt = tag & 7;
      var valStart = i;
      try {
        if (wt === 0) {
          i = readVarint(buf, i)[1];
        } else if (wt === 1) {
          i += 8;
        } else if (wt === 2) {
          var lenPair = readVarint(buf, i);
          i = lenPair[1] + lenPair[0];
          valStart = lenPair[1];
        } else if (wt === 5) {
          i += 4;
        } else {
          parts.push(buf.subarray(fieldStart));
          break;
        }
      } catch (_) {
        parts.push(buf.subarray(fieldStart));
        break;
      }
      if (i > buf.length) {
        parts.push(buf.subarray(fieldStart));
        break;
      }
      var val = buf.subarray(valStart, i);
      var whole = buf.subarray(fieldStart, i);
      var repl = onField(field, wt, val, whole);
      parts.push(repl == null ? whole : repl);
    }
    return Buffer.concat(parts);
  }

  function fieldBytes(field, wt, val) {
    if (wt === 0) return Buffer.concat([writeVarint((field << 3) | 0), val]);
    if (wt === 2) {
      return Buffer.concat([writeVarint((field << 3) | 2), writeVarint(val.length), val]);
    }
    return null;
  }

  function rewriteVarintValue(field, fromVal, toVal, val) {
    var n;
    try {
      n = readVarint(val, 0)[0];
    } catch (_) {
      return null;
    }
    if (n !== fromVal) return null;
    return fieldBytes(field, 0, writeVarint(toVal));
  }

  function payloadLooksLikeGrok(buf) {
    try {
      var s = buf.toString("latin1").toLowerCase();
      if (s.indexOf("grok") < 0) return false;
      return (
        s.indexOf("grok-4.6") >= 0 ||
        s.indexOf("cursor-grok-4.6") >= 0 ||
        s.indexOf("extra-high") >= 0 ||
        s.indexOf("extra_high") >= 0 ||
        s.indexOf("extra high") >= 0 ||
        s.indexOf("-xhigh") >= 0 ||
        s.indexOf("xhigh") >= 0
      );
    } catch (_) {
      return false;
    }
  }

  function agentWindowSources(buf) {
    // 官方 Grok 窗口；若已是 Grok 请求，再吞掉 Auto/Composer 残留上限
    var list = [FROM];
    if (payloadLooksLikeGrok(buf)) {
      list.push(200000, 204800, 128000);
    }
    var toLen = writeVarint(TO).length;
    var out = [];
    for (var i = 0; i < list.length; i++) {
      if (writeVarint(list[i]).length === toLen) out.push(list[i]);
    }
    return out;
  }

  function rewriteAgentPayload(buf, sources) {
    var TOKEN_FIELDS = { 2: 1, 4: 1, 12: 1, 13: 1, 15: 1, 16: 1 };
    if (!sources) sources = agentWindowSources(buf);
    return walkFields(buf, function (field, wt, val) {
      if (wt === 0 && TOKEN_FIELDS[field]) {
        for (var i = 0; i < sources.length; i++) {
          var repl = rewriteVarintValue(field, sources[i], TO, val);
          if (repl) return repl;
        }
        return null;
      }
      if (wt === 2) {
        // 嵌套消息可能没有模型名字符串，沿用外层判定（中途切模型场景）
        var inner = rewriteAgentPayload(val, sources);
        if (inner.equals(val)) return null;
        return fieldBytes(field, 2, inner);
      }
      return null;
    });
  }

  function rewriteStrings256k(buf) {
    var a = Buffer.from("256k context window");
    var b = Buffer.from("500k context window");
    var out = replaceBuf(buf, a, b);
    out = replaceBuf(out, Buffer.from("256k"), Buffer.from("500k"));
    return out;
  }

  function rewriteOneModel(buf) {
    var name = "";
    walkFields(buf, function (field, wt, val) {
      if (field === 1 && wt === 2) {
        try {
          name = val.toString("utf8");
        } catch (_) {}
      }
      return null;
    });
    if (!/grok-4\.6/i.test(name)) return buf;
    var has15 = false;
    var has16 = false;
    var out = walkFields(buf, function (field, wt, val) {
      if ((field === 12 || field === 13 || field === 15 || field === 16) && wt === 0) {
        if (field === 15) has15 = true;
        if (field === 16) has16 = true;
        var n;
        try {
          n = readVarint(val, 0)[0];
        } catch (_) {
          return null;
        }
        if (n === FROM) return fieldBytes(field, 0, writeVarint(TO));
        return null;
      }
      if (wt === 2) {
        var inner = rewriteStrings256k(val);
        if (field !== 1 && inner.equals(val)) {
          inner = rewriteOneModel(val);
        }
        if (inner.equals(val)) return null;
        return fieldBytes(field, 2, inner);
      }
      return null;
    });
    var extras = [];
    if (!has15) extras.push(fieldBytes(15, 0, writeVarint(TO)));
    if (!has16) extras.push(fieldBytes(16, 0, writeVarint(TO)));
    if (extras.length) out = Buffer.concat([out].concat(extras));
    return out;
  }

  function rewriteAvailableModels(buf) {
    return walkFields(buf, function (field, wt, val) {
      if (field === 2 && wt === 2) {
        var inner = rewriteOneModel(val);
        if (inner.equals(val)) return null;
        return fieldBytes(field, 2, inner);
      }
      if (wt === 2) {
        var nested = rewriteAvailableModels(val);
        if (nested.equals(val)) return null;
        return fieldBytes(field, 2, nested);
      }
      return null;
    });
  }

  function rewriteTokenLimit(buf) {
    return walkFields(buf, function (field, wt, val) {
      if (field === 1 && wt === 0) return rewriteVarintValue(field, FROM, TO, val);
      return null;
    });
  }

  function kindFromPath(p) {
    var s = String(p || "");
    if (/AvailableModels/i.test(s)) return "am";
    if (/GetEffectiveTokenLimit/i.test(s)) return "tl";
    if (/AgentService\//i.test(s)) return "agent";
    return "";
  }

  function isTargetPath(p) {
    return !!kindFromPath(p);
  }

  function rewritePayload(buf, kind) {
    if (!buf || !buf.length) return buf;
    try {
      if (kind === "am") return rewriteAvailableModels(buf);
      if (kind === "tl") return rewriteTokenLimit(buf);
      return rewriteAgentPayload(buf);
    } catch (_) {
      return buf;
    }
  }

  function rewriteFrame(frame, kind) {
    if (!frame || frame.length < 5) return frame;
    var flags = frame[0];
    if (flags > 3) return frame;
    var len = frame.readUInt32BE(1);
    if (5 + len > frame.length) return frame;
    var payload = frame.subarray(5, 5 + len);
    var compressed = flags & FLAG_COMPRESSED;
    if (compressed) {
      try {
        payload = zlibMod.gunzipSync(payload);
      } catch (_) {
        try {
          payload = zlibMod.inflateSync(payload);
        } catch (__) {
          return frame;
        }
      }
    }
    var next = rewritePayload(payload, kind);
    var outFlags = flags & FLAG_END_STREAM;
    var out = Buffer.alloc(5 + next.length);
    out[0] = outFlags;
    out.writeUInt32BE(next.length, 1);
    next.copy(out, 5);
    return out;
  }

  function rewriteAllFrames(buf, kind) {
    var i = 0;
    var parts = [];
    var changed = false;
    while (i + 5 <= buf.length) {
      var flags = buf[i];
      if (flags > 3) {
        parts.push(buf.subarray(i));
        break;
      }
      var len = buf.readUInt32BE(i + 1);
      if (i + 5 + len > buf.length) {
        parts.push(buf.subarray(i));
        break;
      }
      var frame = buf.subarray(i, i + 5 + len);
      var next = rewriteFrame(frame, kind);
      if (!next.equals(frame)) changed = true;
      parts.push(next);
      i += 5 + len;
    }
    if (i < buf.length) parts.push(buf.subarray(i));
    return { buf: Buffer.concat(parts), changed: changed };
  }

  function wrapReadable(stream, kind, pathStr) {
    if (!stream || stream[MARK]) return stream;
    stream[MARK] = 1;
    var origPush = stream.push;
    if (typeof origPush !== "function") return stream;
    var pending = Buffer.alloc(0);
    var hits = 0;
    stream.push = function (chunk, enc) {
      if (chunk === null) {
        if (pending.length) {
          origPush.call(this, pending);
          pending = Buffer.alloc(0);
        }
        return origPush.call(this, null);
      }
      var buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, enc);
      pending = Buffer.concat([pending, buf]);
      var out = [];
      while (pending.length >= 5) {
        var flags = pending[0];
        if (flags > 3) {
          out.push(pending);
          pending = Buffer.alloc(0);
          break;
        }
        var len = pending.readUInt32BE(1);
        if (pending.length < 5 + len) break;
        var frame = Buffer.from(pending.subarray(0, 5 + len));
        pending = pending.subarray(5 + len);
        var next = rewriteFrame(frame, kind);
        if (!next.equals(frame)) hits++;
        out.push(next);
      }
      if (hits && out.length) {
        log("rewrite-down " + kind + " path=" + pathStr + " frames=" + out.length + " hits=" + hits);
        hits = 0;
      }
      var ok = true;
      for (var i = 0; i < out.length; i++) {
        if (!origPush.call(this, out[i])) ok = false;
      }
      return ok;
    };
    return stream;
  }

  function wrapWritable(stream, kind, pathStr) {
    if (!stream || stream[MARK + "w"]) return stream;
    var origWrite = stream.write;
    var origEnd = stream.end;
    if (typeof origWrite !== "function") return stream;
    stream[MARK + "w"] = 1;
    var pending = Buffer.alloc(0);
    var hits = 0;

    function take(chunk) {
      if (!chunk || !chunk.length) return [];
      pending = Buffer.concat([pending, Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)]);
      var out = [];
      while (pending.length >= 5) {
        var flags = pending[0];
        if (flags > 3) {
          var raw = pending;
          pending = Buffer.alloc(0);
          var nextRaw = rewritePayload(raw, kind);
          if (!nextRaw.equals(raw)) hits++;
          out.push(nextRaw);
          break;
        }
        var len = pending.readUInt32BE(1);
        if (pending.length < 5 + len) break;
        var frame = Buffer.from(pending.subarray(0, 5 + len));
        pending = pending.subarray(5 + len);
        var next = rewriteFrame(frame, kind);
        if (!next.equals(frame)) hits++;
        out.push(next);
      }
      if (hits) {
        log("rewrite-up " + kind + " path=" + pathStr + " hits=" + hits);
        hits = 0;
      }
      return out;
    }

    stream.write = function (chunk, encoding, cb) {
      if (typeof encoding === "function") {
        cb = encoding;
        encoding = undefined;
      }
      if (chunk === undefined || chunk === null) {
        return origWrite.call(this, chunk, encoding, cb);
      }
      var pieces = take(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, encoding));
      if (!pieces.length) {
        if (typeof cb === "function") process.nextTick(cb);
        return true;
      }
      var payload = Buffer.concat(pieces);
      return origWrite.call(this, payload, undefined, cb);
    };

    stream.end = function (chunk, encoding, cb) {
      if (typeof chunk === "function") {
        cb = chunk;
        chunk = undefined;
        encoding = undefined;
      } else if (typeof encoding === "function") {
        cb = encoding;
        encoding = undefined;
      }
      var parts = [];
      if (chunk !== undefined && chunk !== null) {
        var more = take(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, encoding));
        for (var i = 0; i < more.length; i++) parts.push(more[i]);
      }
      if (pending.length) {
        var rest = rewritePayload(pending, kind);
        pending = Buffer.alloc(0);
        if (rest && rest.length) parts.push(rest);
      }
      if (parts.length) {
        return origEnd.call(this, Buffer.concat(parts), undefined, cb);
      }
      return origEnd.call(this, cb);
    };
    return stream;
  }

  function wrapDuplex(stream, kind, pathStr) {
    wrapReadable(stream, kind, pathStr);
    wrapWritable(stream, kind, pathStr);
    return stream;
  }

  function pathFromHeaders(headers) {
    if (!headers) return "";
    if (Array.isArray(headers)) {
      for (var i = 0; i < headers.length; i += 2) {
        if (String(headers[i]).toLowerCase() === ":path") return String(headers[i + 1] || "");
      }
      return "";
    }
    return String(headers[":path"] || headers[":PATH"] || "");
  }

  function requestArgUrl(a) {
    try {
      if (typeof a === "string") return a;
      if (a && typeof a.href === "string") return String(a.href);
      if (a && typeof a === "object") {
        var proto = a.protocol || "https:";
        if (proto.slice(-1) !== ":") proto += ":";
        var host = a.hostname || a.host || "";
        if (!host) return "";
        return proto + "//" + host + (a.path || a.pathname || "/");
      }
    } catch (_) {}
    return "";
  }

  if (http2Mod && typeof http2Mod.connect === "function") {
    try {
      var origConnect = http2Mod.connect;
      var dummy = origConnect("http://127.0.0.1:1");
      var proto = Object.getPrototypeOf(dummy);
      try {
        dummy.destroy();
      } catch (_) {}
      if (proto && typeof proto.request === "function" && !proto.request[MARK]) {
        var origProtoRequest = proto.request;
        proto.request = function (headers, options) {
          var stream = origProtoRequest.apply(this, arguments);
          var p = pathFromHeaders(headers);
          var kind = kindFromPath(p);
          if (kind) wrapDuplex(stream, kind, p);
          return stream;
        };
        proto.request[MARK] = 1;
        log("hooked http2.ClientHttp2Session.prototype.request");
      }
    } catch (e) {
      log("http2 proto hook failed " + (e && e.message));
    }
  }

  if (httpsMod && typeof httpsMod.request === "function" && !httpsMod.request[MARK]) {
    var origHttps = httpsMod.request;
    function hookedHttps(a, b, c) {
      var url = requestArgUrl(a);
      var kind = kindFromPath(url);
      var cb = typeof c === "function" ? c : typeof b === "function" ? b : undefined;
      function wrapRes(res) {
        if (kind) wrapReadable(res, kind, url);
        return res;
      }
      var args = [a, b, c];
      if (kind && cb) {
        var wrapped = function (res) {
          wrapRes(res);
          return cb.apply(this, arguments);
        };
        if (typeof c === "function") args[2] = wrapped;
        else args[1] = wrapped;
      }
      var req = origHttps.apply(httpsMod, args);
      if (kind) {
        wrapWritable(req, kind, url);
        req.on("response", function (res) {
          wrapRes(res);
        });
      }
      return req;
    }
    hookedHttps[MARK] = 1;
    httpsMod.request = hookedHttps;
    log("hooked https.request");
  }

  try {
    if (typeof G.fetch === "function" && !G.fetch[MARK]) {
      var origFetch = G.fetch.bind(G);
      function hookedFetch(input, init) {
        var url = typeof input === "string" ? input : input && input.url ? String(input.url) : "";
        var kind = kindFromPath(url);
        var p = origFetch(input, init);
        if (!kind) return p;
        return p.then(function (res) {
          if (!res || typeof res.arrayBuffer !== "function") return res;
          return res.arrayBuffer().then(function (ab) {
            var rewritten = rewriteAllFrames(Buffer.from(ab), kind);
            var headers = new Headers(res.headers);
            try {
              headers.delete("content-encoding");
              headers.delete("content-length");
            } catch (_) {}
            return new Response(rewritten.buf, {
              status: res.status,
              statusText: res.statusText,
              headers: headers,
            });
          });
        });
      }
      hookedFetch[MARK] = 1;
      G.fetch = hookedFetch;
      log("hooked fetch");
    }
  } catch (e) {
    log("fetch hook failed " + (e && e.message));
  }

  var api = {
    FROM: FROM,
    TO: TO,
    rewriteFrame: rewriteFrame,
    rewritePayload: rewritePayload,
    rewriteAllFrames: rewriteAllFrames,
    rewriteAgentPayload: rewriteAgentPayload,
    rewriteAvailableModels: rewriteAvailableModels,
    rewriteTokenLimit: rewriteTokenLimit,
    kindFromPath: kindFromPath,
    writeVarint: writeVarint,
  };
  G.__CTXWIN_INSTALLED__ = 1;
  G.__CTXWIN__ = api;
  log("installed FROM=" + FROM + " TO=" + TO + " pid=" + process.pid);
  return api;
}

function hookSource(from, to) {
  return (
    MARK_START +
    "void (" +
    ctxwinInstall.toString() +
    ")(typeof globalThis!=='undefined'?globalThis:global," +
    Number(from) +
    "," +
    Number(to) +
    ");" +
    MARK_END +
    "\n"
  );
}

function sha256(buf) {
  return crypto.createHash("sha256").update(buf).digest("hex");
}

function findCursorAppRoot() {
  const env = process.env.CURSOR_APP_ROOT;
  if (env && fs.existsSync(env)) return env;
  const candidates = [
    "D:\\Tools\\cursor\\resources\\app",
    path.join(process.env.LOCALAPPDATA || "", "Programs", "cursor", "resources", "app"),
    path.join(process.env.LOCALAPPDATA || "", "Programs", "Cursor", "resources", "app"),
  ];
  for (const c of candidates) {
    if (c && fs.existsSync(path.join(c, "out", "vs", "workbench", "api", "node", "extensionHostProcess.js"))) {
      return c;
    }
  }
  throw new Error("找不到 Cursor app root。可设 CURSOR_APP_ROOT。");
}

function targetFiles(appRoot) {
  return [
    path.join(appRoot, "out", "vs", "workbench", "api", "node", "extensionHostProcess.js"),
  ];
}

function stripPatch(text) {
  const start = text.indexOf(MARK_START);
  if (start < 0) return text;
  const end = text.indexOf(MARK_END, start);
  if (end < 0) return text;
  return text.slice(0, start) + text.slice(end + MARK_END.length).replace(/^\r?\n/, "");
}

function atomicWrite(filePath, data) {
  const tmp = filePath + ".ctxwin-tmp";
  fs.writeFileSync(tmp, data);
  fs.renameSync(tmp, filePath);
}

function loadState() {
  if (!fs.existsSync(STATE_PATH)) return null;
  return JSON.parse(fs.readFileSync(STATE_PATH, "utf8"));
}

function cmdSelftest() {
  const api = ctxwinInstall(globalThis, FROM, TO);
  const failures = [];

  function assert(cond, msg) {
    if (!cond) failures.push(msg);
  }

  const vFrom = api.writeVarint(FROM);
  const vTo = api.writeVarint(TO);
  assert(vFrom.length === vTo.length, "varint 256000 与 500000 应等长，现 " + vFrom.length + " vs " + vTo.length);
  assert(vFrom.toString("hex") === "80d00f", "256000 varint 期望 80d00f 实际 " + vFrom.toString("hex"));
  assert(vTo.toString("hex") === "a0c21e", "500000 varint 期望 a0c21e 实际 " + vTo.toString("hex"));

  // ConversationTokenDetails: field1 used=100, field2 max=256000
  const snap = Buffer.concat([
    Buffer.from([0x08, 0x64]),
    Buffer.from([0x10]),
    vFrom,
  ]);
  const snap2 = api.rewriteAgentPayload(snap);
  assert(snap2.indexOf(vTo) >= 0, "Agent payload 应含 500000 varint");
  assert(snap2.indexOf(vFrom) < 0, "Agent payload 不应再含 256000 varint");

  // 中途 Auto→Grok：快照仍是 200000，但包里已有 grok-4.6
  const vAuto = api.writeVarint(200000);
  assert(vAuto.length === vTo.length, "200000 与 500000 varint 应等长");
  const mid = Buffer.concat([
    Buffer.from([0x0a, 8]),
    Buffer.from("grok-4.6"),
    Buffer.from([0x10]),
    vAuto,
  ]);
  const mid2 = api.rewriteAgentPayload(mid);
  assert(mid2.indexOf(vTo) >= 0, "含 grok 时 200000 应改成 500000");
  assert(mid2.indexOf(vAuto) < 0, "含 grok 时不应再留 200000");

  // 无 grok 时不要误改 200000（Composer/Auto）
  const autoOnly = Buffer.concat([Buffer.from([0x10]), vAuto]);
  const autoOnly2 = api.rewriteAgentPayload(autoOnly);
  assert(autoOnly2.indexOf(vAuto) >= 0, "无 grok 时 200000 应保留");
  assert(autoOnly2.indexOf(vTo) < 0, "无 grok 时不应改成 500000");

  // 嵌套 tokenDetails：grok 名在外层，200k 在内层
  const nestedInner = Buffer.concat([Buffer.from([0x10]), vAuto]);
  const nested = Buffer.concat([
    Buffer.from([0x0a, 8]),
    Buffer.from("grok-4.6"),
    Buffer.from([0x12, nestedInner.length]),
    nestedInner,
  ]);
  const nested2 = api.rewriteAgentPayload(nested);
  assert(nested2.indexOf(vTo) >= 0, "嵌套快照含 grok 时内层 200000 应改成 500000");
  assert(nested2.indexOf(vAuto) < 0, "嵌套快照不应再留 200000");

  // gzip Connect frame flags=3 (gzip+END_STREAM)
  const gz = zlib.gzipSync(snap);
  const frame = Buffer.alloc(5 + gz.length);
  frame[0] = 3;
  frame.writeUInt32BE(gz.length, 1);
  gz.copy(frame, 5);
  const out = api.rewriteFrame(frame, "agent");
  assert(out[0] === 2, "回包应去掉 gzip 位、保留 END_STREAM，flags=" + out[0]);
  const outLen = out.readUInt32BE(1);
  const outPayload = out.subarray(5, 5 + outLen);
  assert(outPayload.indexOf(vTo) >= 0, "解压改写后 payload 应含 500000");
  assert(outPayload[0] !== 0x1f, "回包不应再是 gzip");

  // 压缩字节上不应盲替：原 gzip 帧里通常没有明文 80 d0 0f
  const rawHasPlain = gz.indexOf(vFrom) >= 0;
  if (rawHasPlain) {
    console.log("note: 本条 gzip 碰巧含明文 varint（压缩率差），仍走完整帧改写");
  }

  // AvailableModels: one grok-4.6 model with context_token_limit=256000
  const name = Buffer.from("grok-4.6");
  const model = Buffer.concat([
    Buffer.from([0x0a, name.length]),
    name,
    Buffer.from([0x78]),
    vFrom,
  ]);
  const am = Buffer.concat([Buffer.from([0x12, model.length]), model]);
  const am2 = api.rewriteAvailableModels(am);
  assert(am2.indexOf(vTo) >= 0, "AvailableModels grok-4.6 窗口应改成 500000");
  assert(am2.indexOf(Buffer.from("grok-4.6")) >= 0, "模型名应保留");

  // 其它模型的 256000 不动
  const otherName = Buffer.from("claude-4.5");
  const other = Buffer.concat([
    Buffer.from([0x0a, otherName.length]),
    otherName,
    Buffer.from([0x78]),
    vFrom,
  ]);
  const amOther = Buffer.concat([Buffer.from([0x12, other.length]), other]);
  const amOther2 = api.rewriteAvailableModels(amOther);
  assert(amOther2.indexOf(vFrom) >= 0, "非 grok-4.6 的 256000 应保留");
  assert(amOther2.indexOf(vTo) < 0, "非 grok-4.6 不应被改成 500000");

  if (failures.length) {
    console.error("SELFTEST FAIL");
    for (const f of failures) console.error(" - " + f);
    process.exit(1);
  }
  console.log("SELFTEST PASS");
  console.log("  256000 varint", vFrom.toString("hex"));
  console.log("  500000 varint", vTo.toString("hex"));
  console.log("  gzip 帧 flags 3 →", out[0], "payload", outLen, "bytes");
}

function cmdStatus() {
  const appRoot = findCursorAppRoot();
  const files = targetFiles(appRoot);
  const state = loadState();
  console.log("appRoot", appRoot);
  console.log("FROM/TO", FROM, TO);
  console.log("state", state ? state.appliedAt : "(none)");
  for (const f of files) {
    const text = fs.readFileSync(f, "utf8");
    const patched = text.includes(MARK_START);
    console.log((patched ? "PATCHED " : "clean   ") + f);
  }
}

function cmdApply() {
  const appRoot = findCursorAppRoot();
  const files = targetFiles(appRoot);
  fs.mkdirSync(BACKUP_DIR, { recursive: true });
  const hook = hookSource(FROM, TO);
  const state = {
    version: 1,
    from: FROM,
    to: TO,
    appliedAt: new Date().toISOString(),
    appRoot,
    files: [],
  };
  for (const filePath of files) {
    const original = fs.readFileSync(filePath);
    const originalText = original.toString("utf8");
    const clean = stripPatch(originalText);
    const next = hook + clean;
    if (next === originalText) {
      console.log("already patched", filePath);
      state.files.push({
        filePath,
        backup: null,
        sha256Before: sha256(original),
        skipped: true,
      });
      continue;
    }
    const backupName = path.basename(filePath) + "." + sha256(original).slice(0, 16) + ".bak";
    const backupPath = path.join(BACKUP_DIR, backupName);
    if (!fs.existsSync(backupPath)) fs.writeFileSync(backupPath, original);
    atomicWrite(filePath, next);
    state.files.push({
      filePath,
      backup: backupPath,
      sha256Before: sha256(original),
      sha256After: sha256(Buffer.from(next)),
    });
    console.log("patched", filePath);
    console.log("backup ", backupPath);
  }
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
  console.log("apply ok。请完全退出并重启 Cursor。");
  console.log("还原: node \"" + fileURLToPath(import.meta.url) + "\" restore");
}

function cmdRestore() {
  const state = loadState();
  const appRoot = state?.appRoot || findCursorAppRoot();
  const files = state?.files?.length ? state.files : targetFiles(appRoot).map((filePath) => ({ filePath }));
  let restored = 0;
  for (const item of files) {
    const filePath = item.filePath;
    if (!fs.existsSync(filePath)) {
      console.log("missing", filePath);
      continue;
    }
    const current = fs.readFileSync(filePath);
    const text = current.toString("utf8");
    const hasMark = text.includes(MARK_START);
    // Cursor 升级会整文件替换。旧备份不能盖到新版本上，否则会把 IDE 打坏。
    if (!hasMark) {
      console.log("already clean", filePath);
      continue;
    }
    const currentHash = sha256(current);
    const backupOk =
      item.backup &&
      fs.existsSync(item.backup) &&
      item.sha256After &&
      currentHash === item.sha256After;
    if (backupOk) {
      atomicWrite(filePath, fs.readFileSync(item.backup));
      restored++;
      console.log("restored from backup", filePath);
      continue;
    }
    atomicWrite(filePath, stripPatch(text));
    restored++;
    console.log("stripped marker (backup stale or missing)", filePath);
  }
  if (fs.existsSync(STATE_PATH)) fs.unlinkSync(STATE_PATH);
  console.log(restored ? "restore ok。请重启 Cursor。" : "nothing to restore");
}

const cmd = (process.argv[2] || "status").toLowerCase();
if (cmd === "selftest") cmdSelftest();
else if (cmd === "apply") cmdApply();
else if (cmd === "restore" || cmd === "revert" || cmd === "undo") cmdRestore();
else if (cmd === "status") cmdStatus();
else {
  console.error("usage: node patch-ctxwin.mjs apply|restore|status|selftest");
  process.exit(2);
}
