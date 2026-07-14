import type { ReactNode } from "react";
import { SearchField, Input, Button } from "@heroui/react";
import { SelectInput, type Option } from "./FormField";

/** Search box + optional filter selects + arbitrary extra controls. */
export function DataTableToolbar({
  search,
  onSearch,
  searchPlaceholder = "Search…",
  filters,
  children,
}: {
  search?: string;
  onSearch?: (v: string) => void;
  searchPlaceholder?: string;
  filters?: {
    label: string;
    value: string | undefined;
    onChange: (v: string) => void;
    options: Option[];
  }[];
  children?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-3">
      {onSearch && (
        <div className="min-w-[14rem] flex-1">
          <SearchField
            value={search ?? ""}
            onChange={onSearch}
            aria-label="Search"
          >
            <Input placeholder={searchPlaceholder} />
          </SearchField>
        </div>
      )}
      {filters?.map((f) => (
        <div key={f.label} className="min-w-[10rem]">
          <SelectInput
            label={f.label}
            value={f.value}
            onChange={f.onChange}
            options={f.options}
          />
        </div>
      ))}
      {children}
    </div>
  );
}

/** Simple, accessible pager. `page` is 1-based. */
export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav
      className="mt-4 flex items-center justify-between gap-3"
      aria-label="Pagination"
    >
      <p className="text-sm text-muted">
        {from}–{to} of {total}
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          isDisabled={page <= 1}
          onPress={() => onPage(page - 1)}
        >
          Previous
        </Button>
        <span className="text-sm text-muted">
          Page {page} / {pages}
        </span>
        <Button
          variant="outline"
          size="sm"
          isDisabled={page >= pages}
          onPress={() => onPage(page + 1)}
        >
          Next
        </Button>
      </div>
    </nav>
  );
}
