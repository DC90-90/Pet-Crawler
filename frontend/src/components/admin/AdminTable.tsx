import type { ReactNode } from "react";
import { Table } from "@heroui/react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  align?: "start" | "end" | "center";
  className?: string;
}

/** Thin, consistent wrapper over HeroUI Table with horizontal scroll. */
export function AdminTable<T extends { id: string }>({
  columns,
  rows,
  ariaLabel,
}: {
  columns: Column<T>[];
  rows: T[];
  ariaLabel: string;
}) {
  return (
    <Table className="rounded-2xl border border-border bg-surface/40">
      <Table.ScrollContainer>
        <Table.Content aria-label={ariaLabel}>
          <Table.Header>
            {columns.map((c) => (
              <Table.Column key={c.key}>{c.header}</Table.Column>
            ))}
          </Table.Header>
          <Table.Body>
            {rows.map((row) => (
              <Table.Row key={row.id}>
                {columns.map((c) => (
                  <Table.Cell key={c.key} className={c.className}>
                    {c.render(row)}
                  </Table.Cell>
                ))}
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}
