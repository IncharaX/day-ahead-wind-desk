const UK_TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const UK_DATE = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export function formatUkTime(timestamp: string | null | undefined): string {
  return timestamp ? UK_TIME.format(new Date(timestamp)) : "n/a";
}

export function formatUkDate(timestamp: string | null | undefined): string {
  return timestamp ? UK_DATE.format(new Date(timestamp)) : "n/a";
}
