export async function nativeAction(body, { resolveSpace, knownMessages, text, background, contactCard }) {
  const { action, spaceId, messageId, path, clear } = body || {};
  if (typeof spaceId !== "string" || !spaceId) throw new Error("spaceId is required");
  const space = await resolveSpace(spaceId);
  const handlers = {
    edit: async () => {
      if (!messageId || typeof body.text !== "string" || !body.text.trim()) {
        throw new Error("messageId and text are required");
      }
      const target = knownMessages.get(messageId) ?? await space.getMessage(messageId);
      if (!target || target.direction !== "outbound") {
        throw new Error("only your own outbound messages can be edited");
      }
      await space.edit(target, text(body.text));
      return { messageId };
    },
    "contact-card": async () => {
      await space.send(contactCard());
      return {};
    },
    background: async () => {
      if (!clear && (typeof path !== "string" || !path.startsWith("/"))) {
        throw new Error("an absolute local image path or clear=true is required");
      }
      await space.send(background(clear ? "clear" : path));
      return {};
    },
  };
  const handler = Object.hasOwn(handlers, action) ? handlers[action] : undefined;
  if (!handler) throw new Error("unsupported native action");
  return handler();
}
