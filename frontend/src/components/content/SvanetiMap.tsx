import { MapContainer, TileLayer, CircleMarker, Tooltip, Popup } from "react-leaflet";
import { useDestinations } from "@/lib/queries";
import { useLang } from "@/lib/nav";
import { tt } from "@/i18n";

const TILES =
  import.meta.env.VITE_MAP_TILES_URL ||
  "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";

// Anchor points always shown even before destinations load.
const ANCHORS = [
  { name: "Mestia", lat: 43.0453, lng: 42.7289 },
  { name: "Ushguli", lat: 42.9169, lng: 43.0197 },
];

export function SvanetiMap() {
  const lang = useLang();
  const { data } = useDestinations();
  const points =
    data?.items
      ?.filter((d) => d.coordinates)
      .map((d) => ({
        name: tt(d.name, lang),
        lat: d.coordinates!.lat,
        lng: d.coordinates!.lng,
      })) ?? [];
  const markers = points.length ? points : ANCHORS;

  return (
    <div className="overflow-hidden rounded-2xl border border-border">
      <MapContainer
        center={[43.0, 42.85]}
        zoom={9}
        scrollWheelZoom={false}
        style={{ height: "420px", width: "100%" }}
        aria-label="Map of Svaneti destinations"
      >
        <TileLayer
          url={TILES}
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
        {markers.map((m, i) => (
          <CircleMarker
            key={i}
            center={[m.lat, m.lng]}
            radius={9}
            pathOptions={{ color: "#c07b46", fillColor: "#2f5142", fillOpacity: 0.9, weight: 2 }}
          >
            <Tooltip>{m.name}</Tooltip>
            <Popup>{m.name}</Popup>
          </CircleMarker>
        ))}
      </MapContainer>
      {/* Accessible non-visual fallback list of the mapped locations. */}
      <ul className="sr-only">
        {markers.map((m, i) => (
          <li key={i}>{m.name}</li>
        ))}
      </ul>
    </div>
  );
}
