import { useState } from "react";
import { Button, Chip, Dropdown } from "@heroui/react";
import {
  useMe,
  useUsers,
  useCreateUser,
  useUpdateUser,
  useDeleteUser,
  errMessage,
  type AdminUser,
} from "@/lib/admin";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminTable, type Column } from "@/components/admin/AdminTable";
import { ConfirmDialog } from "@/components/admin/ConfirmDialog";
import { EditorModal } from "@/components/admin/EditorModal";
import {
  LoadingState,
  ErrorState,
  AdminEmptyState,
} from "@/components/admin/AdminEmptyState";
import {
  FieldGrid,
  TextInput,
  SelectInput,
  SwitchInput,
} from "@/components/admin/FormField";

const ROLE_OPTIONS = [
  { value: "editor", label: "Editor" },
  { value: "owner", label: "Owner" },
];

const EMPTY: Partial<AdminUser> = {
  email: "",
  name: "",
  role: "editor",
  isActive: true,
  forcePasswordChange: true,
};

interface DraftUser extends Partial<AdminUser> {
  password?: string;
}

export function Component() {
  const me = useMe();
  const { data, isLoading, isError, error } = useUsers();
  const create = useCreateUser();
  const update = useUpdateUser();
  const remove = useDeleteUser();

  const [editing, setEditing] = useState<DraftUser | null>(null);
  const [toDelete, setToDelete] = useState<AdminUser | null>(null);

  const setField = <K extends keyof DraftUser>(k: K, v: DraftUser[K]) =>
    setEditing((e) => (e ? { ...e, [k]: v } : e));

  const items = data && "items" in data ? data.items : [];

  const save = () => {
    if (!editing) return;
    if (editing.id) {
      update.mutate(
        {
          id: editing.id,
          data: {
            name: editing.name,
            role: editing.role,
            isActive: editing.isActive,
          },
        },
        { onSuccess: () => setEditing(null) },
      );
    } else {
      create.mutate(
        {
          email: editing.email,
          name: editing.name,
          role: editing.role,
          password: editing.password,
          forcePasswordChange: true,
          isActive: editing.isActive,
        },
        { onSuccess: () => setEditing(null) },
      );
    }
  };

  const columns: Column<AdminUser>[] = [
    {
      key: "name",
      header: "Name",
      render: (u) => (
        <button
          type="button"
          onClick={() => setEditing(u)}
          className="text-start font-medium text-foreground hover:text-copper"
        >
          {u.name || u.email}
        </button>
      ),
    },
    {
      key: "email",
      header: "Email",
      render: (u) => <span className="text-sm text-muted">{u.email}</span>,
    },
    {
      key: "role",
      header: "Role",
      render: (u) => (
        <Chip variant="soft" color={u.role === "owner" ? "accent" : "default"}>
          {u.role === "owner" ? "Owner" : "Editor"}
        </Chip>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (u) => (
        <Chip variant="soft" color={u.isActive ? "success" : "default"}>
          {u.isActive ? "Active" : "Inactive"}
        </Chip>
      ),
    },
    {
      key: "lastLoginAt",
      header: "Last login",
      render: (u) => (
        <span className="text-sm text-muted">
          {u.lastLoginAt ? new Date(u.lastLoginAt).toLocaleDateString() : "—"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "end",
      render: (u) => (
        <Dropdown>
            <Button variant="outline" size="sm" isIconOnly aria-label="Actions">
              ⋯
            </Button>
          <Dropdown.Popover>
            <Dropdown.Menu
              onAction={(key) => {
                const k = String(key);
                if (k === "edit") setEditing(u);
                else if (k === "toggle")
                  update.mutate({ id: u.id, data: { isActive: !u.isActive } });
                else if (k === "delete") setToDelete(u);
              }}
            >
              <Dropdown.Item id="edit">Edit</Dropdown.Item>
              <Dropdown.Item id="toggle">
                {u.isActive ? "Deactivate" : "Activate"}
              </Dropdown.Item>
              <Dropdown.Item id="delete">Delete</Dropdown.Item>
            </Dropdown.Menu>
          </Dropdown.Popover>
        </Dropdown>
      ),
    },
  ];

  // Owner guard: while loading `me`, show a loading state; otherwise gate on role.
  if (me.isLoading) {
    return (
      <div>
        <AdminPageHeader title="Users" />
        <LoadingState />
      </div>
    );
  }

  if (me.data?.role !== "owner") {
    return (
      <div>
        <AdminPageHeader title="Users" />
        <ErrorState message="Only owners can manage users." />
      </div>
    );
  }

  return (
    <div>
      <AdminPageHeader
        title="Users"
        description="Manage owner and editor accounts."
        actions={
          <Button variant="primary" size="sm" onPress={() => setEditing({ ...EMPTY })}>
            New user
          </Button>
        }
      />

      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState message={errMessage(error)} />
      ) : items.length === 0 ? (
        <AdminEmptyState
          title="No users yet"
          action={
            <Button variant="primary" onPress={() => setEditing({ ...EMPTY })}>
              New user
            </Button>
          }
        />
      ) : (
        <AdminTable columns={columns} rows={items} ariaLabel="Users" />
      )}

      <EditorModal
        isOpen={!!editing}
        onOpenChange={(open) => !open && setEditing(null)}
        title={editing?.id ? "Edit user" : "New user"}
        onSave={save}
        isSaving={create.isPending || update.isPending}
        size="sm"
      >
        {editing && (
          <>
            <FieldGrid>
              <TextInput
                label="Email"
                type="email"
                value={editing.email ?? ""}
                onChange={(v) => setField("email", v)}
                isRequired
                isDisabled={!!editing.id}
              />
              <TextInput
                label="Name"
                value={editing.name ?? ""}
                onChange={(v) => setField("name", v)}
              />
              <SelectInput
                label="Role"
                value={editing.role}
                onChange={(v) => setField("role", v as AdminUser["role"])}
                options={ROLE_OPTIONS}
              />
              {!editing.id && (
                <TextInput
                  label="Password"
                  type="password"
                  value={editing.password ?? ""}
                  onChange={(v) => setField("password", v)}
                  hint="User must change on first login"
                />
              )}
            </FieldGrid>
            <SwitchInput
              label="Active"
              value={editing.isActive ?? true}
              onChange={(v) => setField("isActive", v)}
            />
          </>
        )}
      </EditorModal>

      <ConfirmDialog
        isOpen={!!toDelete}
        onOpenChange={(open) => !open && setToDelete(null)}
        title="Delete user?"
        body={`"${toDelete?.name || toDelete?.email || ""}" will lose access permanently.`}
        destructive
        confirmLabel="Delete"
        isPending={remove.isPending}
        onConfirm={() =>
          toDelete && remove.mutate(toDelete.id, { onSuccess: () => setToDelete(null) })
        }
      />
    </div>
  );
}
