import test from "node:test";
import assert from "node:assert/strict";
import { text } from "spectrum-ts";
import { background, nativeContactCard } from "spectrum-ts/providers/imessage";
import { nativeAction } from "./native-actions.mjs";

test("native edit uses the real target and refuses somebody else's message", async () => {
  const target = { id: "message", direction: "outbound", content: { type: "text", text: "old" } };
  let edited;
  const deps = {
    resolveSpace: async () => ({ edit: async (...args) => { edited = args; } }),
    knownMessages: new Map([["message", target]]), text, background, contactCard: nativeContactCard,
  };
  const result = await nativeAction({ action: "edit", spaceId: "chat", messageId: "message", text: "new" }, deps);
  assert.equal(result.messageId, "message");
  assert.equal(edited[0], target);
  assert.ok(edited[1]); // installed SDK builder, not a fabricated content object
  target.direction = "inbound";
  await assert.rejects(nativeAction({ action: "edit", spaceId: "chat", messageId: "message", text: "new" }, deps));
});

test("opt-in native builders send once and unsupported actions never send", async () => {
  const sends = [];
  const deps = {
    resolveSpace: async () => ({ send: async (value) => sends.push(value) }),
    knownMessages: new Map(), text, background, contactCard: nativeContactCard,
  };
  await nativeAction({ action: "contact-card", spaceId: "chat" }, deps);
  await nativeAction({ action: "background", spaceId: "chat", clear: true }, deps);
  assert.equal(sends.length, 2);
  assert.ok(sends.every(Boolean));
  await assert.rejects(nativeAction({ action: "unknown", spaceId: "chat" }, deps));
  await assert.rejects(nativeAction({ action: "constructor", spaceId: "chat" }, deps));
  await assert.rejects(nativeAction({ action: "background", spaceId: "chat", path: "../secret" }, deps));
  assert.equal(sends.length, 2);
});
