import test from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";

const commands = [];
let deferred = null;
let attachDeferred = null;
const detachCalls = [];
const debuggerEvents = [];

globalThis.chrome = {
  permissions: { contains: async () => true },
  runtime: { getPlatformInfo: async () => ({ os: "win" }) },
  debugger: {
    attach: async () => attachDeferred ? attachDeferred.promise : undefined,
    detach: async ({ tabId }) => { detachCalls.push(tabId); },
    sendCommand(_target, method, params = {}) {
      commands.push({ method, params });
      if (deferred && deferred.match(method, params)) return deferred.promise;
      return Promise.resolve({});
    },
    onEvent: { addListener: (listener) => { debuggerEvents.push(listener); } },
    onDetach: { addListener: () => {} },
  },
};

const source = path.resolve("extension/src/cdp.js");
const cdp = await import(`${pathToFileURL(source).href}?authorization-test=${Date.now()}`);

function nextDeferred(match) {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  deferred = { match, promise, resolve };
  return deferred;
}

async function waitForCommand(predicate) {
  for (let i = 0; i < 50; i++) {
    const found = commands.find(predicate);
    if (found) return found;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  throw new Error("expected debugger command was not dispatched");
}

test("trusted click revalidates after the asynchronous mouse move", async () => {
  commands.length = 0;
  let authorized = true;
  const moved = nextDeferred((method, params) =>
    method === "Input.dispatchMouseEvent" && params.type === "mouseMoved");
  const action = cdp.click(101, 10, 20, () => {
    if (!authorized) throw new Error("authorization changed");
  });
  await waitForCommand(({ method, params }) =>
    method === "Input.dispatchMouseEvent" && params.type === "mouseMoved");
  authorized = false;
  moved.resolve({});
  await assert.rejects(action, /authorization changed/);
  assert.equal(commands.some(({ params }) => params.type === "mousePressed"), false);
  deferred = null;
});

test("trusted type revalidates after select-all before inserting text", async () => {
  commands.length = 0;
  let authorized = true;
  const keyUp = nextDeferred((method, params) =>
    method === "Input.dispatchKeyEvent" && params.type === "keyUp");
  const action = cdp.typeText(102, "private text", () => {
    if (!authorized) throw new Error("authorization changed");
  });
  await waitForCommand(({ method, params }) =>
    method === "Input.dispatchKeyEvent" && params.type === "keyUp");
  authorized = false;
  keyUp.resolve({});
  await assert.rejects(action, /authorization changed/);
  assert.equal(commands.some(({ method }) => method === "Input.insertText"), false);
  deferred = null;
});

test("a revoked binding is detached if authorization changes during debugger attach", async () => {
  commands.length = 0;
  detachCalls.length = 0;
  let resolveAttach;
  attachDeferred = { promise: new Promise((resolve) => { resolveAttach = resolve; }) };
  let authorized = true;
  const action = cdp.hover(103, 10, 20, () => {
    if (!authorized) throw new Error("authorization changed");
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  authorized = false;
  resolveAttach();
  await assert.rejects(action, /authorization changed/);
  assert.deepEqual(detachCalls, [103]);
  assert.equal(commands.some(({ method }) => method.startsWith("Input.")), false);
  attachDeferred = null;
});

test("a native dialog is never handled after tab authorization is revoked", async () => {
  commands.length = 0;
  detachCalls.length = 0;
  let authorized = true;
  await cdp.hover(104, 10, 20, () => {
    if (!authorized) throw new Error("authorization changed");
  });
  commands.length = 0;
  authorized = false;
  for (const listener of debuggerEvents) {
    listener({ tabId: 104 }, "Page.javascriptDialogOpening", {
      type: "beforeunload", message: "Leave this page?",
    });
  }
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(detachCalls, [104]);
  assert.equal(commands.some(({ method }) => method === "Page.handleJavaScriptDialog"), false);
});
