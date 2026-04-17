import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { toast } from "sonner";
import { Plus, RefreshCw, Trash2, Globe, ChevronDown, ChevronUp, AlertCircle, CheckCircle2, Clock, XCircle, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const PLATFORMS = ["salla", "zid", "shopify", "woocommerce", "custom"];

function CrawlStatusBadge({ status }) {
  if (!status) return <Badge variant="outline" className="text-[10px] text-gray-400">No crawl</Badge>;
  const map = {
    success: { icon: CheckCircle2, cls: "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/20" },
    failed: { icon: XCircle, cls: "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/20" },
    unsupported: { icon: AlertCircle, cls: "bg-yellow-50 text-yellow-700 border-yellow-200" },
  };
  const cfg = map[status] || map.failed;
  const Icon = cfg.icon;
  return (
    <Badge variant="outline" className={`text-[10px] capitalize gap-1 ${cfg.cls}`}>
      <Icon className="w-3 h-3" />{status}
    </Badge>
  );
}

function TierBadge({ tier }) {
  if (!tier) return <span className="text-[10px] text-gray-400">-</span>;
  const cls = { 1: "tier-1", 2: "tier-2", 3: "tier-3" };
  return <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${cls[tier] || ""}`}>T{tier}</span>;
}

export default function StoreRegistryPage() {
  const { t } = useI18n();
  const [stores, setStores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ name: "", domain: "", platform: "salla", crawl_frequency_hrs: 24 });
  const [crawling, setCrawling] = useState({});
  const [expandedStore, setExpandedStore] = useState(null);
  const [crawlLogs, setCrawlLogs] = useState({});
  const [crawlPaused, setCrawlPaused] = useState(false);
  const navigate = useNavigate();

  const fetchStores = useCallback(() => {
    setLoading(true);
    api.get("/stores").then((r) => {
      const data = r.data;
      if (Array.isArray(data)) { setStores(data); }
      else { setStores(data.stores || []); setCrawlPaused(data.crawl_paused || false); }
    }).catch(() => toast.error("Failed to load stores")).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchStores(); }, [fetchStores]);

  const handleSave = async () => {
    if (!form.name || !form.domain) { toast.error("Name and domain required"); return; }
    try {
      await api.post("/stores", form);
      toast.success("Store added");
      setDialogOpen(false);
      setForm({ name: "", domain: "", platform: "salla", crawl_frequency_hrs: 24 });
      fetchStores();
    } catch (e) { toast.error(e.response?.data?.detail || "Failed to add store"); }
  };

  const handleDelete = async (store) => {
    if (!window.confirm(`Delete ${store.name}?`)) return;
    try {
      await api.delete(`/stores/${store.id}`);
      toast.success("Store removed");
      fetchStores();
    } catch (err) { console.error(err); toast.error("Failed to delete"); }
  };

  const handleCrawl = async (store) => {
    setCrawling((p) => ({ ...p, [store.id]: true }));
    try {
      const r = await api.post(`/stores/${store.id}/crawl`);
      if (r.data.tier_used) {
        toast.success(`Crawl succeeded for ${store.name} (Tier ${r.data.tier_used}): ${r.data.products_found} products found, ${r.data.products_new} new`);
      } else {
        toast.error(`Crawl failed for ${store.name}: ${r.data.error || "Unknown error"}`);
      }
      fetchStores();
      // Refresh crawl logs if expanded
      if (expandedStore === store.id) fetchCrawlLogs(store.id);
    } catch (e) { toast.error("Crawl request failed"); }
    finally { setCrawling((p) => ({ ...p, [store.id]: false })); }
  };

  const fetchCrawlLogs = async (storeId) => {
    try {
      const r = await api.get(`/stores/${storeId}/crawl-logs?limit=5`);
      setCrawlLogs((prev) => ({ ...prev, [storeId]: r.data }));
    } catch (err) { /* crawl log fetch */  }
  };

  const toggleExpand = (storeId) => {
    if (expandedStore === storeId) {
      setExpandedStore(null);
    } else {
      setExpandedStore(storeId);
      fetchCrawlLogs(storeId);
    }
  };

  const formatDate = (iso) => {
    if (!iso) return "-";
    return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };

  return (
    <div className="p-6 space-y-5" data-testid="store-registry-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">{t("nav_stores")}</h1>
          <p className="text-sm text-[#9CA3AF] mt-0.5">Manage tracked competitor stores</p>
        </div>
        <div className="flex gap-2">
          <Button variant={crawlPaused ? "destructive" : "outline"} size="sm"
            onClick={async () => {
              try { const r = await api.post("/scheduler/toggle-pause"); setCrawlPaused(r.data.crawl_paused); toast.success(r.data.message); }
              catch { toast.error("Failed"); }
            }}
            className="rounded-md text-xs" data-testid="pause-crawls-btn">
            {crawlPaused ? "Resume All Crawls" : "Pause All Crawls"}
          </Button>
          <Button size="sm" onClick={() => setDialogOpen(true)} className="bg-[#00D4B4] hover:bg-[#00E5C3] text-white rounded-md text-xs" data-testid="add-store-btn">
            <Plus className="w-3.5 h-3.5 me-1.5" />{t("btn_add_store")}
          </Button>
        </div>
      </div>

      <div className="glass-card rounded-md overflow-hidden">
        <Table className="dense-table">
          <TableHeader>
            <TableRow className="bg-[#111827]/80/5">
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("store_name")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("col_domain")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("col_platform")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("col_products_count")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Crawl Status</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Tier</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("col_last_crawled")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Next Crawl</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Tier 4</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF] text-end">{t("col_actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={10} className="text-center py-12 text-[#9CA3AF] text-sm">{t("loading")}</TableCell></TableRow>
            ) : stores.length === 0 ? (
              <TableRow><TableCell colSpan={10} className="text-center py-12 text-[#9CA3AF] text-sm">{t("no_data")}</TableCell></TableRow>
            ) : stores.map((s) => (
              <TableRow key={s.id} data-testid={`store-row-${s.id}`} className="hover:bg-[#111827]/80/5 transition-colors group">
                <TableCell>
                  <div className="flex items-center gap-2.5">
                    <div className="w-7 h-7 bg-[#00D4B4] text-[#0A0F1E] text-[10px] font-bold rounded flex items-center justify-center">{s.name?.[0]?.toUpperCase()}</div>
                    <div>
                      <span className="text-sm font-medium text-[#00D4B4] cursor-pointer hover:underline" onClick={() => navigate(`/stores/${s.id}`)}>{s.name}</span>
                      {s.last_crawl_error && (
                        <p className="text-[10px] text-red-400 truncate max-w-[180px]" title={s.last_crawl_error}>{s.last_crawl_error}</p>
                      )}
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <a href={`https://${s.domain}`} target="_blank" rel="noopener noreferrer" className="text-xs text-[#00D4B4] hover:underline flex items-center gap-1">
                    <Globe className="w-3 h-3" />{s.domain}
                  </a>
                </TableCell>
                <TableCell><Badge variant="outline" className="text-[10px] capitalize rounded-md">{s.platform}</Badge></TableCell>
                <TableCell><span className="text-sm font-medium">{s.product_count ?? 0}</span></TableCell>
                <TableCell><CrawlStatusBadge status={s.last_crawl_status} /></TableCell>
                <TableCell>
                  <div>
                    <TierBadge tier={s.last_crawl_tier} />
                    {s.last_crawl_endpoint && s.last_crawl_endpoint !== "none — tier 2 stub" && (
                      <p className="text-[9px] text-[#9CA3AF] mt-0.5 font-mono truncate max-w-[100px]" title={s.last_crawl_endpoint}>{s.last_crawl_endpoint}</p>
                    )}
                  </div>
                </TableCell>
                <TableCell><span className="text-xs text-[#9CA3AF]">{formatDate(s.last_crawled_at)}</span></TableCell>
                <TableCell>
                  <div>
                    <span className="text-xs text-[#9CA3AF]">{s.crawl_frequency_label}</span>
                    {s.next_crawl_at && !crawlPaused && (
                      <p className="text-[9px] text-[#9CA3AF]">{formatDate(s.next_crawl_at)}</p>
                    )}
                    {crawlPaused && <p className="text-[9px] text-red-400">Paused</p>}
                  </div>
                </TableCell>
                <TableCell>
                  {s.tier4_session_status === "active" ? (
                    <Badge variant="outline" className="text-[9px] gap-1 bg-[#10B981]/10 text-[#10B981] border-[#10B981]/20"><Shield className="w-3 h-3" />Authenticated</Badge>
                  ) : s.tier4_session_status === "otp_required" ? (
                    <Badge variant="outline" className="text-[9px] gap-1 bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/20"><Shield className="w-3 h-3" />OTP Needed</Badge>
                  ) : s.tier4_session_status === "expired" ? (
                    <Badge variant="outline" className="text-[9px] gap-1 bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/20 cursor-pointer" onClick={() => navigate("/settings")}><Shield className="w-3 h-3" />Expired</Badge>
                  ) : (
                    <Badge variant="outline" className="text-[9px] gap-1 text-gray-400 cursor-pointer" onClick={() => navigate("/settings")}><Shield className="w-3 h-3" />Not Set Up</Badge>
                  )}
                </TableCell>
                <TableCell className="text-end">
                  <div className="flex items-center gap-1 justify-end">
                    <Button variant="ghost" size="sm" onClick={() => toggleExpand(s.id)} className="h-7 w-7 p-0 opacity-60 hover:opacity-100" data-testid={`expand-btn-${s.id}`}>
                      {expandedStore === s.id ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => handleCrawl(s)} disabled={crawling[s.id]} className="h-7 w-7 p-0" data-testid={`crawl-btn-${s.id}`}>
                      <RefreshCw className={`w-3.5 h-3.5 ${crawling[s.id] ? "animate-sync" : ""}`} />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(s)} className="h-7 w-7 p-0 text-red-500 hover:text-red-600 hover:bg-[#EF4444]/10" data-testid={`delete-store-${s.id}`}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {/* Crawl Log Expansion */}
        {expandedStore && crawlLogs[expandedStore] && (
          <div className="border-t border-white/10 bg-[#111827]/80/5 px-6 py-4" data-testid="crawl-log-panel">
            <h4 className="text-xs font-semibold text-white mb-2">Recent Crawl History</h4>
            <div className="space-y-2">
              {crawlLogs[expandedStore].length === 0 && <p className="text-xs text-[#9CA3AF]">No crawl history yet</p>}
              {crawlLogs[expandedStore].map((log) => (
                <div key={log.id} className="glass-card rounded-md px-3 py-2 space-y-1">
                  <div className="flex items-center gap-4 text-xs">
                    <span className="text-[#9CA3AF] w-[110px] shrink-0">{formatDate(log.completed_at)}</span>
                    <TierBadge tier={log.tier_used} />
                    <span className={`font-medium ${log.tier_used ? "text-green-600" : "text-red-500"}`}>
                      {log.tier_used ? "Success" : "Failed"}
                    </span>
                    {log.endpoint_used && <span className="text-[10px] font-mono text-[#00D4B4]">{log.endpoint_used}</span>}
                    <span className="text-[#9CA3AF]">{log.products_found} found</span>
                    {log.products_new > 0 && <span className="text-green-600">+{log.products_new} new</span>}
                    {log.snapshots_created > 0 && <span className="text-[#00D4B4]">{log.snapshots_created} snapshots</span>}
                  </div>
                  {log.endpoints_tried && log.endpoints_tried.length > 0 && (
                    <div className="flex flex-wrap gap-2 ps-[110px]">
                      {log.endpoints_tried.map((ep) => (
                        <span key={`${ep.endpoint}-${ep.status}`} className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${ep.products > 0 ? "bg-[#10B981]/10 text-[#10B981]" : "bg-[#EF4444]/10 text-[#EF4444]"}`} title={ep.error || ""}>
                          {ep.endpoint} → {ep.status || "err"} {ep.products > 0 ? `(${ep.products})` : ""}
                        </span>
                      ))}
                    </div>
                  )}
                  {log.error && <p className="text-[10px] text-red-400 ps-[110px] truncate" title={log.error}>{log.error}</p>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Add Store Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md rounded-md" data-testid="add-store-dialog">
          <DialogHeader>
            <DialogTitle className="font-bold">{t("btn_add_store")}</DialogTitle>
            <DialogDescription>Add a new Saudi pet store to track</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <label className="text-xs font-medium text-white mb-1 block">{t("store_name")}</label>
              <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="e.g. Zarafa" className="rounded-md" data-testid="store-name-input" />
            </div>
            <div>
              <label className="text-xs font-medium text-white mb-1 block">{t("col_domain")}</label>
              <Input value={form.domain} onChange={(e) => setForm((f) => ({ ...f, domain: e.target.value }))} placeholder="e.g. zarafaksa.com" className="rounded-md" data-testid="store-domain-input" />
            </div>
            <div>
              <label className="text-xs font-medium text-white mb-1 block">{t("col_platform")}</label>
              <Select value={form.platform} onValueChange={(v) => setForm((f) => ({ ...f, platform: v }))}>
                <SelectTrigger className="rounded-md" data-testid="store-platform-select"><SelectValue /></SelectTrigger>
                <SelectContent>{PLATFORMS.map((p) => <SelectItem key={p} value={p} className="capitalize">{p}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-white mb-1 block">{t("crawl_frequency")}</label>
              <Input type="number" value={form.crawl_frequency_hrs} onChange={(e) => setForm((f) => ({ ...f, crawl_frequency_hrs: parseInt(e.target.value) || 24 }))} className="rounded-md" data-testid="store-freq-input" />
            </div>
          </div>
          <DialogFooter className="relative z-[60]">
            <Button variant="outline" size="sm" onClick={() => setDialogOpen(false)} className="rounded-md" type="button">{t("btn_cancel")}</Button>
            <Button size="sm" onClick={handleSave} className="bg-[#00D4B4] hover:bg-[#00E5C3] text-white rounded-md" data-testid="store-save-btn" type="button">{t("btn_save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
