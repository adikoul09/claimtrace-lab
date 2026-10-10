import { test } from "node:test";
import assert from "node:assert/strict";
import { getLastRead, markRead, mergeEmails, unreadCount } from "./inbox.ts";

const ev = (id: string, ts: string, type = "email_received") => ({ id, ts, type, message: id, data: {} });

test("mergeEmails keeps only email_received events, newest first, once each", () => {
  const cur = [ev("a", "2026-10-10T10:00:00Z")];
  const merged = mergeEmails(cur, [
    ev("b", "2026-10-10T11:00:00Z"),
    ev("a", "2026-10-10T10:00:00Z"),
    ev("c", "2026-10-10T12:00:00Z", "feedback"),
  ]);
  assert.deepEqual(
    merged.map((e) => e.id),
    ["b", "a"],
  );
});

test("unreadCount counts emails newer than the last read time; nothing read means all unread", () => {
  const emails = [ev("b", "2026-10-10T11:00:00Z"), ev("a", "2026-10-10T10:00:00Z")];
  assert.equal(unreadCount(emails, null), 2);
  assert.equal(unreadCount(emails, "2026-10-10T10:00:00Z"), 1);
  assert.equal(unreadCount(emails, "2026-10-10T11:00:00+00:00"), 0);
});

test("markRead stores the read time per project and only moves it forward", () => {
  const store = new Map<string, string>();
  const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
  markRead("p1", "2026-10-10T11:00:00Z", storage);
  markRead("p1", "2026-10-10T10:00:00Z", storage);
  assert.equal(getLastRead("p1", storage), "2026-10-10T11:00:00Z");
  assert.equal(getLastRead("p2", storage), null);
});

test("read state still works in memory when storage throws (blocked or private mode)", () => {
  const blocked = {
    getItem: () => {
      throw new Error("SecurityError");
    },
    setItem: () => {
      throw new Error("QuotaExceededError");
    },
  };
  markRead("p3", "2026-10-10T09:00:00Z", blocked);
  assert.equal(getLastRead("p3", blocked), "2026-10-10T09:00:00Z");
  assert.equal(getLastRead("p3", null), "2026-10-10T09:00:00Z");
});
