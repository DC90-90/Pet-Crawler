export const ObservedAt = ({ value, id }) => <time dateTime={value || undefined} title={value || "No observation timestamp"}
  className="block text-[10px] text-[#A1E4DB] whitespace-normal break-words" data-testid={id}>
  {value ? `Observed ${new Date(value).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Riyadh" })} KSA` : "Observation timestamp unavailable"}
</time>;