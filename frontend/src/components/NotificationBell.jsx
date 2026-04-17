import { useState, useEffect, useCallback, useRef } from "react";
import api from "@/lib/api";
import { Bell, AlertTriangle, ShoppingCart, TrendingDown, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";

const TYPE_ICONS = {
  price_drop: TrendingDown,
  out_of_stock: ShoppingCart,
  back_in_stock: AlertTriangle,
};

export default function NotificationBell() {
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const fetchNotifications = useCallback(async () => {
    try {
      const r = await api.get("/notifications");
      setData(r.data);
    } catch {}
  }, []);

  useEffect(() => { fetchNotifications(); const iv = setInterval(fetchNotifications, 30000); return () => clearInterval(iv); }, [fetchNotifications]);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const totalCount = data?.total_alerts || 0;

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="relative p-2 rounded-xl hover:bg-white/5 transition-colors" data-testid="notification-bell">
        <Bell className="w-5 h-5 text-[#9CA3AF]" />
        {totalCount > 0 && (
          <span className="absolute -top-0.5 -end-0.5 w-5 h-5 rounded-full bg-[#EF4444] text-white text-[9px] font-bold flex items-center justify-center">
            {totalCount > 99 ? "99+" : totalCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute end-0 top-12 w-[380px] glass-card border border-white/10 rounded-xl shadow-2xl z-50 max-h-[500px] overflow-hidden animate-fadeIn" data-testid="notification-panel">
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
            <div>
              <h3 className="text-sm font-semibold text-white">Notifications</h3>
              <p className="text-[10px] text-[#9CA3AF]">{totalCount} active alerts ({data?.auto_generated || 0} auto-generated)</p>
            </div>
            <button onClick={() => setOpen(false)} className="text-[#9CA3AF] hover:text-white"><X className="w-4 h-4" /></button>
          </div>
          <div className="overflow-y-auto max-h-[400px] divide-y divide-white/5">
            {(!data?.notifications || data.notifications.length === 0) ? (
              <div className="px-4 py-8 text-center text-[#9CA3AF] text-sm">No notifications yet. Go to Settings to auto-generate alerts.</div>
            ) : data.notifications.map((n) => {
              const Icon = TYPE_ICONS[n.type] || AlertTriangle;
              const typeCls = n.type === "price_drop" ? "text-[#EF4444]" : n.type === "out_of_stock" ? "text-[#F59E0B]" : "text-[#00D4B4]";
              return (
                <div key={n.id} className="px-4 py-3 hover:bg-white/3 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className={`mt-0.5 ${typeCls}`}><Icon className="w-4 h-4" /></div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-white font-medium truncate">{n.product_name}</p>
                      <p className="text-[10px] text-[#9CA3AF] mt-0.5 line-clamp-2">{n.description}</p>
                    </div>
                    <Badge className={`text-[8px] shrink-0 border-0 ${n.type === "price_drop" ? "bg-[#EF4444]/10 text-[#EF4444]" : n.type === "out_of_stock" ? "bg-[#F59E0B]/10 text-[#F59E0B]" : "bg-[#00D4B4]/10 text-[#00D4B4]"}`}>
                      {n.type === "price_drop" ? "Price" : n.type === "out_of_stock" ? "OOS" : "Gap"}
                    </Badge>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
