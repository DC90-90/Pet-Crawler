import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { toast } from "sonner";
import { Plus, RefreshCw, Pencil, Trash2, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const PLATFORMS = ["salla", "zid", "shopify", "woocommerce", "custom"];

export default function StoreRegistryPage() {
  const { t } = useI18n();
  const [stores, setStores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ name: "", domain: "", platform: "salla", crawl_frequency_hrs: 24 });
  const [crawling, setCrawling] = useState({});

  const fetchStores = useCallback(() => {
    setLoading(true);
    api.get("/stores").then((r) => setStores(r.data)).catch(() => toast.error("Failed to load stores")).finally(() => setLoading(false));
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
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to add store");
    }
  };

  const handleDelete = async (store) => {
    if (!window.confirm(`Delete ${store.name}?`)) return;
    try {
      await api.delete(`/stores/${store.id}`);
      toast.success("Store removed");
      fetchStores();
    } catch { toast.error("Failed to delete"); }
  };

  const handleCrawl = async (store) => {
    setCrawling((p) => ({ ...p, [store.id]: true }));
    try {
      const r = await api.post(`/stores/${store.id}/crawl`);
      toast.success(r.data.message);
      fetchStores();
    } catch { toast.error("Crawl failed"); }
    finally { setCrawling((p) => ({ ...p, [store.id]: false })); }
  };

  const formatDate = (iso) => {
    if (!iso) return "-";
    return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };

  return (
    <div className="p-6 space-y-5" data-testid="store-registry-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#0A0A0A]">{t("nav_stores")}</h1>
          <p className="text-sm text-[#9CA3AF] mt-0.5">Manage tracked competitor stores</p>
        </div>
        <Button size="sm" onClick={() => setDialogOpen(true)}
          className="bg-[#002DF5] hover:bg-blue-700 text-white rounded-md text-xs"
          data-testid="add-store-btn">
          <Plus className="w-3.5 h-3.5 me-1.5" />{t("btn_add_store")}
        </Button>
      </div>

      <div className="bg-white border border-[#E5E7EB] rounded-md overflow-hidden">
        <Table className="dense-table">
          <TableHeader>
            <TableRow className="bg-[#F9FAFB]">
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("store_name")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("col_domain")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("col_platform")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("col_products_count")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("col_frequency")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{t("col_last_crawled")}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF] text-end">{t("col_actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={7} className="text-center py-12 text-[#9CA3AF] text-sm">{t("loading")}</TableCell></TableRow>
            ) : stores.length === 0 ? (
              <TableRow><TableCell colSpan={7} className="text-center py-12 text-[#9CA3AF] text-sm">{t("no_data")}</TableCell></TableRow>
            ) : stores.map((s) => (
              <TableRow key={s.id} data-testid={`store-row-${s.id}`} className="hover:bg-[#F9FAFB] transition-colors">
                <TableCell>
                  <div className="flex items-center gap-2.5">
                    <div className="w-7 h-7 bg-[#002DF5] text-white text-[10px] font-bold rounded flex items-center justify-center">
                      {s.name?.[0]?.toUpperCase()}
                    </div>
                    <span className="text-sm font-medium text-[#0A0A0A]">{s.name}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <a href={`https://${s.domain}`} target="_blank" rel="noopener noreferrer" className="text-xs text-[#002DF5] hover:underline flex items-center gap-1">
                    <Globe className="w-3 h-3" />{s.domain}
                  </a>
                </TableCell>
                <TableCell><Badge variant="outline" className="text-[10px] capitalize rounded-md">{s.platform}</Badge></TableCell>
                <TableCell><span className="text-sm font-medium">{s.product_count ?? 0}</span></TableCell>
                <TableCell><span className="text-xs text-[#4B5563]">{s.crawl_frequency_hrs}h</span></TableCell>
                <TableCell><span className="text-xs text-[#9CA3AF]">{formatDate(s.last_crawled_at)}</span></TableCell>
                <TableCell className="text-end">
                  <div className="flex items-center gap-1 justify-end">
                    <Button variant="ghost" size="sm" onClick={() => handleCrawl(s)} disabled={crawling[s.id]}
                      className="h-7 w-7 p-0" data-testid={`crawl-btn-${s.id}`}>
                      <RefreshCw className={`w-3.5 h-3.5 ${crawling[s.id] ? "animate-sync" : ""}`} />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(s)}
                      className="h-7 w-7 p-0 text-red-500 hover:text-red-600 hover:bg-red-50" data-testid={`delete-store-${s.id}`}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
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
              <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">{t("store_name")}</label>
              <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="e.g. Zarafa" className="rounded-md" data-testid="store-name-input" />
            </div>
            <div>
              <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">{t("col_domain")}</label>
              <Input value={form.domain} onChange={(e) => setForm((f) => ({ ...f, domain: e.target.value }))} placeholder="e.g. zarafaksa.com" className="rounded-md" data-testid="store-domain-input" />
            </div>
            <div>
              <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">{t("col_platform")}</label>
              <Select value={form.platform} onValueChange={(v) => setForm((f) => ({ ...f, platform: v }))}>
                <SelectTrigger className="rounded-md" data-testid="store-platform-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PLATFORMS.map((p) => <SelectItem key={p} value={p} className="capitalize">{p}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">{t("crawl_frequency")}</label>
              <Input type="number" value={form.crawl_frequency_hrs} onChange={(e) => setForm((f) => ({ ...f, crawl_frequency_hrs: parseInt(e.target.value) || 24 }))} className="rounded-md" data-testid="store-freq-input" />
            </div>
          </div>
          <DialogFooter className="relative z-[60]">
            <Button variant="outline" size="sm" onClick={() => setDialogOpen(false)} className="rounded-md" type="button">{t("btn_cancel")}</Button>
            <Button size="sm" onClick={handleSave} className="bg-[#002DF5] hover:bg-blue-700 text-white rounded-md" data-testid="store-save-btn" type="button">{t("btn_save")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
