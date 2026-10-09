import test from "node:test";
import assert from "node:assert/strict";
import { sendWithOptionalReply } from "./send-thread.mjs";
import { reply, text } from "spectrum-ts";

const target = { id: "parent-1", content: { type: "text", text: "source" }, direction: "inbound" };
async function exercise(anchor, found) {
  const calls = [], lookups = [];
  const result = await sendWithOptionalReply(
    { send: async value => { calls.push(value); return { id: "out-1" }; } },
    { type: "text", text: "answer" }, anchor,
    async id => { lookups.push(id); return found ? target : undefined; },
    (content, parent) => ({ type: "reply", content, target: parent }),
  );
  return { calls, lookups, result };
}
test("resolved parent sends a native threaded reply", async () => {
  const result = await exercise("parent-1", true);
  assert.deepEqual(result.lookups, ["parent-1"]);
  assert.deepEqual(result.calls, [{ type: "reply", content: { type: "text", text: "answer" }, target }]);
  assert.equal(result.result.id, "out-1");
});
test("missing parent safely falls back to an unthreaded message", async () => {
  const result = await exercise("missing", false);
  assert.deepEqual(result.lookups, ["missing"]);
  assert.deepEqual(result.calls, [{ type: "text", text: "answer" }]);
});
test("unanchored send does not look up a parent", async () => {
  const result = await exercise(null, true);
  assert.deepEqual(result.lookups, []);
  assert.deepEqual(result.calls, [{ type: "text", text: "answer" }]);
});
test("the installed Spectrum builder accepts the message target", async () => {
  const calls = [];
  const result = await sendWithOptionalReply(
    { send: async value => { calls.push(await value.build()); return { id: "out-1" }; } },
    text("answer"), "parent-1", async () => target, reply,
  );
  assert.deepEqual(calls, [{ type: "reply", content: { type: "text", text: "answer" }, target }]);
  assert.equal(result.id, "out-1");
});
