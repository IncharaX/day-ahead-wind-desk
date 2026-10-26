import { afterEach, describe, expect, it } from "vitest";

import { formatUkTime } from "./time";

const originalTimezone = process.env.TZ;

afterEach(() => {
  process.env.TZ = originalTimezone;
});

describe("formatUkTime", () => {
  it.each(["Asia/Kolkata", "America/New_York"])(
    "formats UK time independently of %s",
    (timezone) => {
      process.env.TZ = timezone;
      expect(formatUkTime("2026-01-16T19:00:00Z")).toBe("19:00");
    },
  );
});
