import { useRelease } from "@/contexts/ReleaseContext";
import { ObservationNotice } from "@/components/ReleaseBoundary";

export default function ReleaseStatusPage() {
  const r = useRelease();
  return <div className="p-6 space-y-6" data-testid="release-status-page">
    <h1 className="text-4xl text-white font-bold">Release status</h1>
    <ObservationNotice />
    <dl className="grid gap-5 sm:grid-cols-2 text-sm">
      {[["Release", r.release_id], ["Source commit", r.git_commit || "Not yet committed"], ["Build manifest", r.manifest_verified ? "Verified source manifest" : "Unstamped workspace"],
        ["Write mode", r.mode], ["Scheduler", r.scheduler_authority], ["Writer ownership", r.scheduler_owner || "Unclaimed; scheduled writes disabled"]].map(([k,v]) =>
        <div key={k} className="min-w-0" data-testid={`release-field-${k.toLowerCase().replaceAll(" ", "-")}`}><dt className="text-[#A1E4DB]">{k}</dt><dd className="text-white break-all mt-1">{v}</dd></div>)}
    </dl>
    <h2 className="text-base md:text-lg font-semibold text-white">Capabilities</h2>
    <div className="divide-y divide-white/10">
      {Object.entries(r.capabilities).map(([name,on]) => <div key={name} className="flex justify-between gap-4 py-3 text-sm" data-testid={`capability-${name.replaceAll("_","-")}`}>
        <span className="text-[#A1E4DB]">{name.replaceAll("_"," ")}</span><span className={on ? "text-emerald-400" : "text-amber-300"}>{on ? "Enabled" : "Disabled"}</span>
      </div>)}
    </div>
  </div>;
}