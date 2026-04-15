import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Plus, RefreshCw, Pencil, Trash2, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const PLATFORMS = ["Salla", "Zid", "Shopify", "WooCommerce", "Magento", "Other"];

function SyncStatusBadge({ status }) {
  const styles = {
    synced: "bg-green-50 text-green-700 border-green-200",
    syncing: "bg-yellow-50 text-yellow-700 border-yellow-200",
    failed: "bg-red-50 text-red-700 border-red-200",
    pending: "bg-gray-50 text-gray-600 border-gray-200",
  };
  return (
    <div className="flex items-center gap-2">
      <span className={`status-dot ${status}`} />
      <Badge
        variant="outline"
        className={`text-[11px] capitalize ${styles[status] || styles.pending}`}
      >
        {status}
      </Badge>
    </div>
  );
}

export default function CompetitorsPage() {
  const [competitors, setCompetitors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingComp, setEditingComp] = useState(null);
  const [form, setForm] = useState({ name: "", platform: "", website_url: "" });
  const [syncing, setSyncing] = useState({});

  const fetchCompetitors = useCallback(() => {
    setLoading(true);
    axios
      .get(`${API}/competitors`)
      .then((r) => setCompetitors(r.data))
      .catch(() => toast.error("Failed to load competitors"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchCompetitors();
  }, [fetchCompetitors]);

  const openAddDialog = () => {
    setEditingComp(null);
    setForm({ name: "", platform: "", website_url: "" });
    setDialogOpen(true);
  };

  const openEditDialog = (comp) => {
    setEditingComp(comp);
    setForm({ name: comp.name, platform: comp.platform, website_url: comp.website_url });
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!form.name || !form.platform) {
      toast.error("Name and platform are required");
      return;
    }
    try {
      if (editingComp) {
        await axios.put(`${API}/competitors/${editingComp.id}`, form);
        toast.success("Competitor updated");
      } else {
        await axios.post(`${API}/competitors`, form);
        toast.success("Competitor added");
      }
      setDialogOpen(false);
      fetchCompetitors();
    } catch {
      toast.error("Failed to save competitor");
    }
  };

  const handleDelete = async (comp) => {
    if (!window.confirm(`Delete ${comp.name}? This will also remove all tracked products.`)) return;
    try {
      await axios.delete(`${API}/competitors/${comp.id}`);
      toast.success("Competitor removed");
      fetchCompetitors();
    } catch {
      toast.error("Failed to delete");
    }
  };

  const handleSync = async (comp) => {
    setSyncing((prev) => ({ ...prev, [comp.id]: true }));
    try {
      const r = await axios.post(`${API}/sync/trigger/${comp.id}`);
      toast.success(r.data.message);
      fetchCompetitors();
    } catch {
      toast.error("Sync failed");
    } finally {
      setSyncing((prev) => ({ ...prev, [comp.id]: false }));
    }
  };

  const handleSyncAll = async () => {
    setSyncing((prev) => ({ ...prev, all: true }));
    try {
      const r = await axios.post(`${API}/sync/trigger-all`);
      toast.success(r.data.message);
      fetchCompetitors();
    } catch {
      toast.error("Sync all failed");
    } finally {
      setSyncing((prev) => ({ ...prev, all: false }));
    }
  };

  const formatDate = (iso) => {
    if (!iso) return "Never";
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className="p-6 lg:p-8 space-y-6" data-testid="competitors-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-heading font-semibold tracking-tight text-foreground">
            Competitors
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage and monitor pet store competitors
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleSyncAll}
            disabled={syncing.all}
            className="text-sm rounded-sm"
            data-testid="sync-all-btn"
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${syncing.all ? "animate-spin" : ""}`} />
            Sync All
          </Button>
          <Button
            size="sm"
            onClick={openAddDialog}
            className="bg-[#002CFA] hover:bg-[#001FD1] text-white rounded-sm text-sm"
            data-testid="competitor-add-btn"
          >
            <Plus className="w-3.5 h-3.5 mr-1.5" />
            Add Competitor
          </Button>
        </div>
      </div>

      <div className="bg-white border border-border rounded-sm overflow-hidden">
        <Table className="dense-table">
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="font-heading text-xs uppercase tracking-wider">Store</TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">Platform</TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">Products</TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">Sync Status</TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">Last Synced</TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-12 text-muted-foreground">
                  Loading...
                </TableCell>
              </TableRow>
            ) : competitors.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center py-12">
                  <img
                    src="https://static.prod-images.emergentagent.com/jobs/e703fccc-0c9e-4960-bc7a-841f7b4e9557/images/0d7e3378028be99612eeff64c9aa7c7891b1189248d635feac4b981aba59c56f.png"
                    alt="Empty state"
                    className="w-32 h-32 mx-auto mb-3 opacity-80"
                  />
                  <p className="text-sm text-muted-foreground">No competitors yet. Add your first competitor.</p>
                </TableCell>
              </TableRow>
            ) : (
              competitors.map((comp) => (
                <TableRow
                  key={comp.id}
                  data-testid={`competitor-row-${comp.id}`}
                  className="transition-colors"
                >
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 bg-[#002CFA] text-white text-xs font-bold rounded-sm flex items-center justify-center">
                        {comp.logo_initial}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-foreground">{comp.name}</p>
                        {comp.website_url && (
                          <a
                            href={comp.website_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[11px] text-muted-foreground hover:text-[#002CFA] flex items-center gap-0.5"
                          >
                            {comp.website_url.replace("https://", "")}
                            <ExternalLink className="w-2.5 h-2.5" />
                          </a>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-[11px] rounded-sm">
                      {comp.platform}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-sm font-medium">{comp.total_products}</TableCell>
                  <TableCell>
                    <SyncStatusBadge status={comp.sync_status} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatDate(comp.last_synced)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center gap-1 justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleSync(comp)}
                        disabled={syncing[comp.id]}
                        className="h-7 w-7 p-0"
                        data-testid={`sync-btn-${comp.id}`}
                      >
                        <RefreshCw className={`w-3.5 h-3.5 ${syncing[comp.id] ? "animate-spin" : ""}`} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEditDialog(comp)}
                        className="h-7 w-7 p-0"
                        data-testid={`edit-btn-${comp.id}`}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(comp)}
                        className="h-7 w-7 p-0 text-red-500 hover:text-red-600 hover:bg-red-50"
                        data-testid={`delete-btn-${comp.id}`}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Add/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md rounded-sm" data-testid="competitor-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">
              {editingComp ? "Edit Competitor" : "Add Competitor"}
            </DialogTitle>
            <DialogDescription>
              {editingComp ? "Update competitor details" : "Add a new pet store competitor to track"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="text-xs font-medium text-foreground mb-1.5 block">Store Name</label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Zarafa"
                className="rounded-sm"
                data-testid="competitor-name-input"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-foreground mb-1.5 block">Platform</label>
              <Select
                value={form.platform}
                onValueChange={(v) => setForm((f) => ({ ...f, platform: v }))}
              >
                <SelectTrigger className="rounded-sm" data-testid="competitor-platform-select">
                  <SelectValue placeholder="Select platform" />
                </SelectTrigger>
                <SelectContent>
                  {PLATFORMS.map((p) => (
                    <SelectItem key={p} value={p}>{p}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-xs font-medium text-foreground mb-1.5 block">Website URL</label>
              <Input
                value={form.website_url}
                onChange={(e) => setForm((f) => ({ ...f, website_url: e.target.value }))}
                placeholder="https://store.sa"
                className="rounded-sm"
                data-testid="competitor-url-input"
              />
            </div>
          </div>
          <DialogFooter className="relative z-[60]">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setDialogOpen(false)}
              className="rounded-sm"
              data-testid="competitor-cancel-btn"
              type="button"
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              className="bg-[#002CFA] hover:bg-[#001FD1] text-white rounded-sm"
              data-testid="competitor-save-btn"
              type="button"
            >
              {editingComp ? "Update" : "Add Competitor"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
