import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { ShieldCheck, UserPlus, Trash2, KeyRound, ChevronDown, ChevronRight, Lock, AlertCircle } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/App";

const PAGE_LABELS = {
  my_products: "My Products",
  price_intel: "Price Intel",
  insights: "Insights",
  scanner: "Price Scanner",
  market_share: "Market Share",
  discounts: "Discounts",
  alerts: "Alerts",
  stores: "Stores",
  import: "Import",
  settings: "Settings",
};

const ROLE_LABELS = { super_admin: "Super Admin", admin: "Admin", user: "User" };

function RoleBadge({ role }) {
  const tone = role === "super_admin"
    ? { bg: "#FBBF2422", border: "#FBBF24", color: "#FBBF24" }
    : role === "admin"
      ? { bg: "#1E988E22", border: "#1E988E", color: "#6AC1B5" }
      : { bg: "#A1E4DB11", border: "#13625F", color: "#A1E4DB" };
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider rounded"
      style={{ background: tone.bg, border: `1px solid ${tone.border}`, color: tone.color, fontFamily: "'JetBrains Mono', monospace" }}
      data-testid={`role-badge-${role}`}
    >
      {role === "super_admin" && <Lock className="w-2.5 h-2.5" />}
      {ROLE_LABELS[role] || role}
    </span>
  );
}

function CreateUserForm({ allPages, onCreated }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ email: "", password: "", name: "", role: "user", allowed_pages: [] });
  const [saving, setSaving] = useState(false);

  const togglePage = (key) => {
    setForm((f) => ({
      ...f,
      allowed_pages: f.allowed_pages.includes(key)
        ? f.allowed_pages.filter((p) => p !== key)
        : [...f.allowed_pages, key],
    }));
  };

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post("/admin/users", form);
      toast.success(`Created user ${form.email}`);
      setForm({ email: "", password: "", name: "", role: "user", allowed_pages: [] });
      setOpen(false);
      onCreated();
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Failed to create user");
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <Button
        onClick={() => setOpen(true)}
        className="hrm-btn-primary inline-flex items-center gap-2 px-4 py-2 text-xs"
        data-testid="open-create-user-btn"
      >
        <UserPlus className="w-4 h-4" /> Add user
      </Button>
    );
  }

  return (
    <form onSubmit={submit} className="p-5 mb-5 rounded border" style={{ background: "#0A2728", borderColor: "#13625F" }} data-testid="create-user-form">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "#FFFFFF", fontFamily: "'Space Grotesk', sans-serif" }}>New user</h3>
        <button type="button" onClick={() => setOpen(false)} className="text-xs hover:underline" style={{ color: "#A1E4DB" }} data-testid="close-create-user-btn">Cancel</button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        <div>
          <label className="text-[10px] uppercase tracking-wider mb-1 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>Email *</label>
          <Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required placeholder="user@company.sa" className="hrm-input h-10" data-testid="create-user-email" />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-wider mb-1 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>Password *</label>
          <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={6} placeholder="min 6 chars" className="hrm-input h-10" data-testid="create-user-password" />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-wider mb-1 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>Name</label>
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Display name" className="hrm-input h-10" data-testid="create-user-name" />
        </div>
        <div>
          <label className="text-[10px] uppercase tracking-wider mb-1 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>Role</label>
          <select
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
            className="w-full h-10 px-3 text-sm rounded"
            style={{ background: "#090E1C", color: "#FFFFFF", border: "1px solid #13625F" }}
            data-testid="create-user-role"
          >
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
        </div>
      </div>

      <div className="mb-4">
        <p className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>Allowed pages</p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {allPages.map((p) => (
            <label key={p} className="flex items-center gap-2 cursor-pointer text-xs" style={{ color: "#FFFFFF" }}>
              <input
                type="checkbox"
                checked={form.allowed_pages.includes(p)}
                onChange={() => togglePage(p)}
                className="accent-[#1E988E]"
                data-testid={`create-page-${p}`}
              />
              {PAGE_LABELS[p] || p}
            </label>
          ))}
        </div>
        <p className="text-[10px] mt-2" style={{ color: "#A1E4DB", opacity: 0.6 }}>
          Leave empty for zero access (user can only see the no-access screen).
        </p>
      </div>

      <Button type="submit" disabled={saving} className="hrm-btn-primary px-5 py-2 text-xs" data-testid="submit-create-user">
        {saving ? "Creating..." : "Create user"}
      </Button>
    </form>
  );
}

function UserRow({ u, allPages, onChange }) {
  const [expanded, setExpanded] = useState(false);
  const [pwForm, setPwForm] = useState({ value: "", saving: false });
  const [pages, setPages] = useState(u.allowed_pages || []);
  const [role, setRole] = useState(u.role);
  const [saving, setSaving] = useState(false);

  useEffect(() => { setPages(u.allowed_pages || []); setRole(u.role); }, [u]);

  const locked = u.is_super_admin;

  const togglePage = (key) => {
    setPages((arr) => (arr.includes(key) ? arr.filter((p) => p !== key) : [...arr, key]));
  };

  const savePages = async () => {
    setSaving(true);
    try {
      await api.patch(`/admin/users/${u.id}/pages`, { allowed_pages: pages });
      toast.success("Pages updated");
      onChange();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to update pages");
    } finally {
      setSaving(false);
    }
  };

  const saveRole = async (newRole) => {
    setRole(newRole);
    try {
      await api.patch(`/admin/users/${u.id}/role`, { role: newRole });
      toast.success(`Role set to ${newRole}`);
      onChange();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to update role");
      setRole(u.role);
    }
  };

  const savePassword = async (e) => {
    e.preventDefault();
    if (pwForm.value.length < 6) {
      toast.error("Password must be at least 6 characters");
      return;
    }
    setPwForm((f) => ({ ...f, saving: true }));
    try {
      await api.patch(`/admin/users/${u.id}/password`, { password: pwForm.value });
      toast.success(`Password reset for ${u.email}`);
      setPwForm({ value: "", saving: false });
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to update password");
      setPwForm((f) => ({ ...f, saving: false }));
    }
  };

  const deleteUser = async () => {
    if (!window.confirm(`Delete user ${u.email}? This cannot be undone.`)) return;
    try {
      await api.delete(`/admin/users/${u.id}`);
      toast.success(`Deleted ${u.email}`);
      onChange();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to delete");
    }
  };

  return (
    <div className="rounded border mb-2" style={{ background: "#0A2728", borderColor: "#13625F" }} data-testid={`user-row-${u.id}`}>
      <div className="flex items-center justify-between p-4">
        <button
          type="button"
          onClick={() => !locked && setExpanded((v) => !v)}
          className="flex items-center gap-3 text-left flex-1"
          data-testid={`user-toggle-${u.id}`}
        >
          {locked ? <Lock className="w-4 h-4" style={{ color: "#FBBF24" }} /> : (expanded ? <ChevronDown className="w-4 h-4" style={{ color: "#A1E4DB" }} /> : <ChevronRight className="w-4 h-4" style={{ color: "#A1E4DB" }} />)}
          <div>
            <p className="text-sm" style={{ color: "#FFFFFF" }}>{u.name || u.email.split("@")[0]}</p>
            <p className="text-[11px]" style={{ color: "#A1E4DB", opacity: 0.7, fontFamily: "'JetBrains Mono', monospace" }}>{u.email}</p>
          </div>
        </button>
        <div className="flex items-center gap-3">
          <RoleBadge role={u.role} />
          <span className="text-[11px]" style={{ color: "#A1E4DB" }} data-testid={`user-pages-count-${u.id}`}>
            {u.is_super_admin ? "ALL PAGES" : `${u.allowed_pages?.length || 0} / ${allPages.length} pages`}
          </span>
          {!locked && (
            <button
              onClick={deleteUser}
              className="p-2 rounded hover:bg-[#EF4444]/10 transition"
              style={{ color: "#EF4444" }}
              title="Delete user"
              data-testid={`delete-user-${u.id}`}
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {locked && (
        <div className="px-4 pb-4 -mt-2">
          <div className="flex items-start gap-2 p-3 rounded text-[11px]" style={{ background: "#FBBF2410", border: "1px solid #FBBF2440", color: "#FBBF24" }}>
            <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span>
              Super admin is immutable. Cannot be deleted, demoted, or have pages revoked. Only the super admin can change their own password (via this page when signed in as themselves).
            </span>
          </div>
        </div>
      )}

      {expanded && !locked && (
        <div className="px-4 pb-4 space-y-4" style={{ borderTop: "1px solid #13625F" }}>
          <div className="pt-4">
            <label className="text-[10px] uppercase tracking-wider mb-2 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>Role</label>
            <select
              value={role}
              onChange={(e) => saveRole(e.target.value)}
              className="h-9 px-3 text-sm rounded"
              style={{ background: "#090E1C", color: "#FFFFFF", border: "1px solid #13625F" }}
              data-testid={`role-select-${u.id}`}
            >
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-wider mb-2 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>Allowed pages</label>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-3">
              {allPages.map((p) => (
                <label key={p} className="flex items-center gap-2 cursor-pointer text-xs" style={{ color: "#FFFFFF" }}>
                  <input
                    type="checkbox"
                    checked={pages.includes(p)}
                    onChange={() => togglePage(p)}
                    className="accent-[#1E988E]"
                    data-testid={`edit-page-${u.id}-${p}`}
                  />
                  {PAGE_LABELS[p] || p}
                </label>
              ))}
            </div>
            <div className="flex gap-2">
              <Button onClick={savePages} disabled={saving} className="hrm-btn-primary px-4 py-1.5 text-xs" data-testid={`save-pages-${u.id}`}>
                {saving ? "Saving..." : "Save pages"}
              </Button>
              <button
                type="button"
                onClick={() => setPages(allPages)}
                className="text-[11px] underline"
                style={{ color: "#A1E4DB" }}
                data-testid={`grant-all-${u.id}`}
              >
                Grant all
              </button>
              <button
                type="button"
                onClick={() => setPages([])}
                className="text-[11px] underline"
                style={{ color: "#A1E4DB" }}
                data-testid={`revoke-all-${u.id}`}
              >
                Revoke all
              </button>
            </div>
          </div>

          <form onSubmit={savePassword} className="flex items-end gap-2">
            <div className="flex-1">
              <label className="text-[10px] uppercase tracking-wider mb-2 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>Reset password</label>
              <Input
                type="password"
                value={pwForm.value}
                onChange={(e) => setPwForm({ ...pwForm, value: e.target.value })}
                placeholder="New password (min 6 chars)"
                className="hrm-input h-9"
                data-testid={`pw-input-${u.id}`}
              />
            </div>
            <Button type="submit" disabled={pwForm.saving || pwForm.value.length < 6} className="hrm-btn-primary px-4 py-1.5 text-xs inline-flex items-center gap-1.5" data-testid={`pw-save-${u.id}`}>
              <KeyRound className="w-3.5 h-3.5" />
              {pwForm.saving ? "Saving..." : "Update"}
            </Button>
          </form>
        </div>
      )}
    </div>
  );
}

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const [data, setData] = useState({ users: [], all_pages: [], valid_roles: [] });
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const { data: resp } = await api.get("/admin/users");
      setData(resp);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const filtered = data.users.filter((u) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return u.email.toLowerCase().includes(q) || (u.name || "").toLowerCase().includes(q);
  });

  // Sort: super_admin first, then admin, then user, then by email
  filtered.sort((a, b) => {
    const order = { super_admin: 0, admin: 1, user: 2 };
    const ro = (order[a.role] ?? 9) - (order[b.role] ?? 9);
    if (ro !== 0) return ro;
    return a.email.localeCompare(b.email);
  });

  return (
    <div className="p-6 space-y-5" data-testid="users-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-[0.05em] uppercase" style={{ color: "#FFFFFF", fontFamily: "'Space Grotesk', sans-serif" }}>
            <ShieldCheck className="inline-block w-6 h-6 me-2" style={{ color: "#1E988E" }} />
            User Management
          </h1>
          <p className="text-xs" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>
            Super admin only. Signed in as <span style={{ color: "#6AC1B5" }}>{currentUser?.email}</span>
          </p>
        </div>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by email or name..."
          className="hrm-input h-10 max-w-xs"
          data-testid="users-search"
        />
      </div>

      <CreateUserForm allPages={data.all_pages} onCreated={fetchUsers} />

      <div data-testid="users-list">
        {loading && <p className="text-xs" style={{ color: "#A1E4DB" }}>Loading...</p>}
        {!loading && filtered.length === 0 && (
          <p className="text-xs p-6 text-center rounded" style={{ color: "#A1E4DB", background: "#0A2728", border: "1px solid #13625F" }}>
            No users match your search.
          </p>
        )}
        {filtered.map((u) => (
          <UserRow key={u.id} u={u} allPages={data.all_pages} onChange={fetchUsers} />
        ))}
      </div>
    </div>
  );
}
