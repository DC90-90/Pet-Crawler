import { useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { toast } from "sonner";
import { Upload, FileSpreadsheet, CheckCircle2, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function ImportPage() {
  const { isRTL } = useI18n();
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [matching, setMatching] = useState(false);
  const [matchResult, setMatchResult] = useState(null);
  const [status, setStatus] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await api.get("/import/status");
      setStatus(r.data);
    } catch {}
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await api.post("/import/products", form, { headers: { "Content-Type": "multipart/form-data" }, timeout: 120000 });
      setImportResult(r.data);
      toast.success(`Imported ${r.data.imported} products`);
      fetchStatus();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Import failed");
    } finally {
      setUploading(false);
    }
  };

  const handleMatch = async () => {
    setMatching(true);
    try {
      const r = await api.post("/import/run-matching");
      setMatchResult(r.data);
      toast.success("Matching engine started");
      const poll = setInterval(async () => {
        const s = await api.get("/import/status");
        setStatus(s.data);
        if (s.data.matching_job?.status === "complete") {
          clearInterval(poll);
          setMatching(false);
          toast.success(`Matching complete: ${s.data.total_matches} matches found`);
        }
      }, 5000);
      setTimeout(() => clearInterval(poll), 300000);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Matching failed");
      setMatching(false);
    }
  };

  return (
    <div className="p-6 space-y-6" data-testid="import-page">
      <div>
        <h1 className="text-2xl font-semibold text-white">{isRTL ? "استيراد المنتجات" : "Import Products"}</h1>
        <p className="text-sm text-[#A1E4DB] mt-1">{isRTL ? "استيراد منتجات متجرك من ملف زيد" : "Import your store products from Zid Excel export"}</p>
      </div>

      {/* Upload Area */}
      <div className="glass-card p-8">
        <div
          className={`border-2 border-dashed rounded-xl p-12 text-center transition-colors ${file ? "border-[#1E988E]/50 bg-[#1E988E]/5" : "border-white/10 hover:border-white/20"}`}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); setFile(e.dataTransfer.files[0]); }}
          data-testid="upload-dropzone"
        >
          {file ? (
            <div className="flex flex-col items-center gap-3">
              <FileSpreadsheet className="w-12 h-12 text-[#1E988E]" />
              <p className="text-white font-medium">{file.name}</p>
              <p className="text-xs text-[#A1E4DB]">{(file.size / 1024 / 1024).toFixed(1)} MB</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3">
              <Upload className="w-12 h-12 text-[#A1E4DB]" />
              <p className="text-[#A1E4DB]">{isRTL ? "اسحب ملف Excel هنا أو" : "Drag Excel file here or"}</p>
            </div>
          )}
          <input type="file" accept=".xlsx,.xls,.csv" className="hidden" id="file-input"
            onChange={(e) => setFile(e.target.files[0])} />
          <label htmlFor="file-input" className="mt-3 inline-block cursor-pointer text-sm text-[#1E988E] hover:underline" data-testid="file-select-btn">
            {isRTL ? "اختر ملف" : "Browse files"}
          </label>
        </div>

        <div className="flex gap-3 mt-5">
          <Button onClick={handleUpload} disabled={!file || uploading}
            className="rounded-full bg-[#1E988E] text-[#090E1C] font-semibold hover:bg-[#6AC1B5] disabled:opacity-40"
            data-testid="upload-btn">
            {uploading ? <><Loader2 className="w-4 h-4 animate-spin mr-2" />{isRTL ? "جارٍ الاستيراد..." : "Importing..."}</> : (isRTL ? "استيراد" : "Import Products")}
          </Button>
          {importResult && (
            <Button onClick={handleMatch} disabled={matching}
              className="rounded-full bg-[#F59E0B] text-[#090E1C] font-semibold hover:bg-[#FBBF24] disabled:opacity-40"
              data-testid="match-btn">
              {matching ? <><Loader2 className="w-4 h-4 animate-spin mr-2" />{isRTL ? "جارٍ المطابقة..." : "Matching..."}</> : <><Play className="w-4 h-4 mr-1" />{isRTL ? "تشغيل المطابقة" : "Run Matching Engine"}</>}
            </Button>
          )}
        </div>
      </div>

      {/* Results */}
      {importResult && (
        <div className="glass-card p-6" data-testid="import-results">
          <div className="flex items-center gap-2 mb-4">
            <CheckCircle2 className="w-5 h-5 text-[#10B981]" />
            <h3 className="text-white font-semibold">{isRTL ? "نتائج الاستيراد" : "Import Results"}</h3>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="kpi-card"><p className="text-[10px] uppercase text-[#A1E4DB] tracking-wider">Imported</p><p className="text-2xl font-bold text-white metric-number">{importResult.imported}</p></div>
            <div className="kpi-card"><p className="text-[10px] uppercase text-[#A1E4DB] tracking-wider">Skipped</p><p className="text-2xl font-bold text-white metric-number">{importResult.skipped}</p></div>
            <div className="kpi-card"><p className="text-[10px] uppercase text-[#A1E4DB] tracking-wider">Total Rows</p><p className="text-2xl font-bold text-white metric-number">{importResult.total_rows}</p></div>
          </div>
        </div>
      )}

      {/* Status */}
      {status && (
        <div className="glass-card p-6" data-testid="status-card">
          <h3 className="text-white font-semibold mb-3">{isRTL ? "حالة النظام" : "System Status"}</h3>
          <div className="grid grid-cols-4 gap-4">
            <div><p className="text-[10px] uppercase text-[#A1E4DB]">My Products</p><p className="text-lg font-bold text-white metric-number">{status.my_products}</p></div>
            <div><p className="text-[10px] uppercase text-[#A1E4DB]">Matches</p><p className="text-lg font-bold text-[#1E988E] metric-number">{status.total_matches}</p></div>
            <div><p className="text-[10px] uppercase text-[#A1E4DB]">Confirmed</p><p className="text-lg font-bold text-[#10B981] metric-number">{status.confirmed_matches}</p></div>
            <div><p className="text-[10px] uppercase text-[#A1E4DB]">Blacklisted</p><p className="text-lg font-bold text-[#EF4444] metric-number">{status.blacklisted}</p></div>
          </div>
        </div>
      )}
    </div>
  );
}
