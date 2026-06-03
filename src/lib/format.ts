export function formatMiles(miles: number): string {
  return miles.toLocaleString();
}

export function formatTaxes(taxes: number | null): string {
  if (taxes == null) return "—";
  const amount = taxes > 1000 ? taxes / 100 : taxes;
  return `$${amount.toFixed(0)}`;
}

export function dealBadge(deal: string): { label: string; className: string } {
  switch (deal) {
    case "great":
      return { label: "Great deal", className: "bg-green-100 text-green-800" };
    case "ok":
      return { label: "Fair", className: "bg-yellow-100 text-yellow-800" };
    case "over":
      return { label: "Over budget", className: "bg-red-100 text-red-800" };
    default:
      return { label: "", className: "" };
  }
}
