import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { toast } from "sonner";
import { Bell, Plus, Trash2, Power, RefreshCw, ArrowDown, ArrowUp, PackageX, PackageCheck, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const ALERT_TYPES = [
  { value: "price_drop", label: "Price Drop", icon: ArrowDown, color: "text-red-500" },
  { value: "price_increase", label: "Price Increase", icon: ArrowUp, color: "text-green-600" },
  { value: "out_of_stock", label: "Out of Stock", icon: PackageX, color: "text-red-500" },
  { value: "back_in_stock", label: "Back in Stock", icon: PackageCheck, color: "text-green-600" },
  { value: "low_stock", label: "Low Stock", icon: AlertTriangle, color: "text-yellow-600" },
];

const CHANNELS = [
  { value: "in_app", label: "In-App" },
  { value: "email", label: "Email (console)" },
];

function AlertTypeIcon({ type }) {
  const cfg = ALERT_TYPES.find((a) => a.value === type) || ALERT_TYPES[0];
  const Icon = cfg.icon;
  return <Icon className={`w-3.5 h-3.5 ${cfg.color}`} />;
}

export default function AlertsPage() {
  const { t } = useI18n();
  const [alerts, setAlerts] = useState([]);
  const [feed, setFeed] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const [products, setProducts] = useState([]);
  const [form, setForm] = useState({ product_sku: "", alert_type: "price_drop", threshold: 5, channel: "in_app" });

  const fetchAll = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get("/alerts"),
      api.get("/alerts/feed?days=30"),
      api.get("/products?limit=200"),
    ]).then(([a, f, p]) => {
      setAlerts(a.data);
      setFeed(f.data);
      setProducts(p.data.products || []);
    }).catch(console.error).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleCreate = async () => {
    if (!form.product_sku) { toast.error("Select a product"); return; }
    try {
      await api.post("/alerts", form);
      toast.success("Alert created");
      setDialogOpen(false);
      setForm({ product_sku: "", alert_type: "price_drop", threshold: 5, channel: "in_app" });
      fetchAll();
    } catch (e) { toast.error(e.response?.data?.detail || "Failed"); }
  };

  const handleDelete = async (id) => {
    try {
      await api.delete(`/alerts/${id}`);
      toast.success("Alert deleted");
      fetchAll();
    } catch (err) { console.error(err); toast.error("Failed"); }
  };

  const handleToggle = async (id) => {
    try {
      await api.put(`/alerts/${id}/toggle`);
      fetchAll();
    } catch (err) { console.error(err); toast.error("Failed"); }
  };

  const handleCheck = async () => {
    setChecking(true);
    try {
      const r = await api.post("/alerts/check");
      toast.success(r.data.message);
      fetchAll();
    } catch (err) { console.error(err); toast.error("Check failed"); }
    finally { setChecking(false); }
  };

  const formatDate = (iso) => {
    if (!iso) return "-";
    return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  };

  if (loading) return <div className="p-6 text-sm text-[#9CA3AF]">{t("loading")}</div>;

  return (
    <div className="p-6 space-y-5" data-testid="alerts-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Alerts</h1>
          <p className="text-sm text-[#9CA3AF] mt-0.5">Monitor price changes and stock events</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleCheck} disabled={checking} className="rounded-md text-xs" data-testid="check-alerts-btn">
            <RefreshCw className={`w-3.5 h-3.5 me-1.5 ${checking ? "animate-sync" : ""}`} />Check Now
          </Button>
          <Button size="sm" onClick={() => setDialogOpen(true)} className="bg-[#00D4B4] hover:bg-[#00E5C3] text-white rounded-md text-xs" data-testid="create-alert-btn">
            <Plus className="w-3.5 h-3.5 me-1.5" />Create Alert
          </Button>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="kpi-card"><p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#9CA3AF]">Active Alerts</p><p className="text-2xl font-bold text-white mt-1">{alerts.filter((a) => a.is_active).length}</p></div>
        <div className="kpi-card"><p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#9CA3AF]">Events (30d)</p><p className="text-2xl font-bold text-white mt-1">{feed.length}</p></div>
        <div className="kpi-card"><p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#9CA3AF]">Total Alerts</p><p className="text-2xl font-bold text-white mt-1">{alerts.length}</p></div>
      </div>

      <Tabs defaultValue="alerts" className="w-full">
        <TabsList className="bg-[#111827]/80/5 p-1 rounded-md">
          <TabsTrigger value="alerts" className="text-xs rounded-md data-[state=active]:bg-[#111827]/80 data-[state=active]:shadow-sm">My Alerts ({alerts.length})</TabsTrigger>
          <TabsTrigger value="feed" className="text-xs rounded-md data-[state=active]:bg-[#111827]/80 data-[state=active]:shadow-sm">Alert Feed ({feed.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="alerts" className="mt-3">
          <div className="glass-card rounded-md overflow-hidden">
            <Table className="dense-table">
              <TableHeader>
                <TableRow className="bg-[#111827]/80/5">
                  <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Type</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Product</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Threshold</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Channel</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Triggered</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Status</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF] text-end">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {alerts.length === 0 ? (
                  <TableRow><TableCell colSpan={7} className="text-center py-12 text-[#9CA3AF] text-sm">No alerts configured. Create your first alert.</TableCell></TableRow>
                ) : alerts.map((a) => (
                  <TableRow key={a.id} data-testid={`alert-row-${a.id}`}>
                    <TableCell><div className="flex items-center gap-1.5"><AlertTypeIcon type={a.alert_type} /><span className="text-xs capitalize">{a.alert_type.replace("_", " ")}</span></div></TableCell>
                    <TableCell>
                      <div><p className="text-xs font-medium text-white">{a.product_name_ar || a.product_sku}</p><p className="text-[10px] text-[#9CA3AF] font-mono">{a.product_sku}</p></div>
                    </TableCell>
                    <TableCell><span className="text-xs">{a.threshold ? `${a.threshold}%` : "-"}</span></TableCell>
                    <TableCell><Badge variant="outline" className="text-[10px] capitalize">{a.channel}</Badge></TableCell>
                    <TableCell><span className="text-xs text-[#9CA3AF]">{a.triggered_count || 0}x</span></TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-[10px] ${a.is_active ? "bg-green-50 text-green-700 border-green-200" : "bg-gray-50 text-gray-500 border-gray-200"}`}>
                        {a.is_active ? "Active" : "Paused"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-end">
                      <div className="flex items-center gap-1 justify-end">
                        <Button variant="ghost" size="sm" onClick={() => handleToggle(a.id)} className="h-7 w-7 p-0" data-testid={`toggle-alert-${a.id}`}>
                          <Power className={`w-3.5 h-3.5 ${a.is_active ? "text-green-500" : "text-gray-400"}`} />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleDelete(a.id)} className="h-7 w-7 p-0 text-red-500 hover:text-red-600 hover:bg-red-50" data-testid={`delete-alert-${a.id}`}>
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        <TabsContent value="feed" className="mt-3">
          <div className="glass-card rounded-md overflow-hidden">
            {feed.length === 0 ? (
              <div className="text-center py-12 text-[#9CA3AF] text-sm">No alert events in the last 30 days</div>
            ) : (
              <div className="divide-y divide-[#E5E7EB]">
                {feed.map((ev) => (
                  <div key={ev.id} className="flex items-center gap-4 px-4 py-3 hover:bg-[#111827]/80/5 transition-colors" data-testid={`feed-event-${ev.id}`}>
                    <AlertTypeIcon type={ev.alert_type} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-white">
                        <span className="capitalize">{ev.alert_type?.replace("_", " ")}</span> - <span className="font-mono">{ev.sku}</span>
                        {ev.store_name && <span className="text-[#9CA3AF]"> at {ev.store_name}</span>}
                      </p>
                      <p className="text-[10px] text-[#9CA3AF]">{ev.old_value} &rarr; {ev.new_value}</p>
                    </div>
                    <span className="text-[10px] text-[#9CA3AF] shrink-0">{formatDate(ev.triggered_at)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>

      {/* Create Alert Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md rounded-md" data-testid="create-alert-dialog">
          <DialogHeader>
            <DialogTitle className="font-bold">Create Alert</DialogTitle>
            <DialogDescription>Get notified when conditions are met</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <label className="text-xs font-medium text-white mb-1 block">Product (SKU)</label>
              <Select value={form.product_sku} onValueChange={(v) => setForm((f) => ({ ...f, product_sku: v }))}>
                <SelectTrigger className="rounded-md" data-testid="alert-sku-select"><SelectValue placeholder="Select product" /></SelectTrigger>
                <SelectContent className="max-h-[200px]">
                  {products.map((p) => <SelectItem key={p.sku} value={p.sku}>{p.name_ar} ({p.sku})</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-white mb-1 block">Alert Type</label>
              <Select value={form.alert_type} onValueChange={(v) => setForm((f) => ({ ...f, alert_type: v }))}>
                <SelectTrigger className="rounded-md" data-testid="alert-type-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ALERT_TYPES.map((a) => <SelectItem key={a.value} value={a.value}>{a.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-white mb-1 block">Threshold (%)</label>
              <Input type="number" value={form.threshold} onChange={(e) => setForm((f) => ({ ...f, threshold: parseFloat(e.target.value) || 0 }))} className="rounded-md" data-testid="alert-threshold-input" />
            </div>
            <div>
              <label className="text-xs font-medium text-white mb-1 block">Channel</label>
              <Select value={form.channel} onValueChange={(v) => setForm((f) => ({ ...f, channel: v }))}>
                <SelectTrigger className="rounded-md" data-testid="alert-channel-select"><SelectValue /></SelectTrigger>
                <SelectContent>{CHANNELS.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter className="relative z-[60]">
            <Button variant="outline" size="sm" onClick={() => setDialogOpen(false)} className="rounded-md" type="button">{t("btn_cancel")}</Button>
            <Button size="sm" onClick={handleCreate} className="bg-[#00D4B4] hover:bg-[#00E5C3] text-white rounded-md" data-testid="alert-save-btn" type="button">Create Alert</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
