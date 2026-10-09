export async function sendWithOptionalReply(
  space,
  content,
  replyToMessageId,
  lookupTarget,
  buildReply
) {
  if (typeof replyToMessageId !== "string" || !replyToMessageId) {
    return space.send(content);
  }

  let target;
  try {
    target = await lookupTarget(replyToMessageId);
  } catch {
    target = undefined;
  }
  if (!target) {
    console.warn("photon-sidecar: reply target unavailable; sending as a new message");
    return space.send(content);
  }

  if (typeof buildReply !== "function") {
    console.warn("photon-sidecar: reply builder unavailable; sending as a new message");
    return space.send(content);
  }

  let reply;
  try {
    reply = buildReply(content, target);
  } catch {
    console.warn("photon-sidecar: reply builder rejected target; sending as a new message");
    return space.send(content);
  }
  return space.send(reply);
}
