export const HistoricalQuantity = ({ quantity, observedAt, id }) => quantity == null ? null : (
  <p className="text-[10px] text-[#A1E4DB] break-words" data-testid={id}>
    Last observed quantity: {quantity} · {observedAt ? new Date(observedAt).toLocaleString() : "observation date unknown"} · not current stock
  </p>
);