/**
 * Reusable "SKU: <value>" inline line.
 * - Label "SKU:" rendered in muted teal (#A1E4DB)
 * - Value in JetBrains Mono, slightly smaller than product name
 * - If `barcode` is provided AND differs from sku, also renders " · EAN: <value>"
 *
 * Usage:
 *   <SkuLine sku={p.sku} barcode={p.barcode} />
 */
export function SkuLine({ sku, barcode, className = "", size = "xs" }) {
  if (!sku && !barcode) return null;
  const sizeCls = size === "sm" ? "text-[11px]" : "text-[10px]";
  const showEan = barcode && barcode !== sku;
  return (
    <p
      data-testid={sku ? `sku-line-${sku}` : "sku-line"}
      className={`${sizeCls} text-[#A1E4DB] tracking-tight ${className}`}
      style={{ fontFamily: "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace" }}
    >
      {sku && (
        <>
          <span className="opacity-70">SKU:&nbsp;</span>
          <span className="text-white/85">{sku}</span>
        </>
      )}
      {showEan && (
        <>
          <span className="opacity-50 mx-1">·</span>
          <span className="opacity-70">EAN:&nbsp;</span>
          <span className="text-white/85">{barcode}</span>
        </>
      )}
    </p>
  );
}
