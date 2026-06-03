"use client";

import type { AwardResult } from "@/lib/seats-aero";
import { formatMiles, formatTaxes, dealBadge } from "@/lib/format";

export default function ResultsTable({
  results,
  query,
}: {
  results: AwardResult[];
  query: string;
}) {
  if (results.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p className="text-lg">No award availability found</p>
        <p className="text-sm mt-1">
          Try broadening your date range, adding more programs, or removing the
          direct-only filter.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900">
          {results.length} result{results.length !== 1 ? "s" : ""} found
        </h2>
        <p className="text-sm text-gray-500">{query}</p>
      </div>

      {results.length > 0 && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-4">
          <p className="text-sm font-medium text-green-800">
            Best: {formatMiles(results[0].miles)} miles +{" "}
            {formatTaxes(results[0].taxes)} on {results[0].program},{" "}
            {results[0].date}
          </p>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="text-left py-3 px-2 font-medium text-gray-600">
                Date
              </th>
              <th className="text-left py-3 px-2 font-medium text-gray-600">
                Program
              </th>
              <th className="text-left py-3 px-2 font-medium text-gray-600">
                Route
              </th>
              <th className="text-right py-3 px-2 font-medium text-gray-600">
                Miles
              </th>
              <th className="text-right py-3 px-2 font-medium text-gray-600">
                Taxes
              </th>
              <th className="text-center py-3 px-2 font-medium text-gray-600">
                Stops
              </th>
              <th className="text-center py-3 px-2 font-medium text-gray-600">
                Deal
              </th>
              <th className="text-center py-3 px-2 font-medium text-gray-600">
                Book
              </th>
            </tr>
          </thead>
          <tbody>
            {results.map((r, i) => {
              const badge = dealBadge(r.deal);
              return (
                <tr
                  key={`${r.id}-${i}`}
                  className="border-b border-gray-100 hover:bg-gray-50 transition-colors"
                >
                  <td className="py-3 px-2 font-medium">{r.date}</td>
                  <td className="py-3 px-2">{r.program}</td>
                  <td className="py-3 px-2 text-gray-600">
                    {r.origin} → {r.destination}
                  </td>
                  <td className="py-3 px-2 text-right font-semibold tabular-nums">
                    {formatMiles(r.miles)}
                  </td>
                  <td className="py-3 px-2 text-right text-gray-600 tabular-nums">
                    {formatTaxes(r.taxes)}
                  </td>
                  <td className="py-3 px-2 text-center">
                    {r.direct ? (
                      <span className="text-green-600 font-medium">
                        Nonstop
                      </span>
                    ) : (
                      <span className="text-gray-400">1+ stop</span>
                    )}
                  </td>
                  <td className="py-3 px-2 text-center">
                    {badge.label && (
                      <span
                        className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${badge.className}`}
                      >
                        {badge.label}
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-2 text-center">
                    <a
                      href={r.bookingLink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:text-blue-800 font-medium"
                    >
                      Book →
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-gray-400 mt-4">
        Award availability is volatile. Confirm miles + fees on the airline site
        before booking.
      </p>
    </div>
  );
}
