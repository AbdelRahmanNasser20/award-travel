"use client";

import { useState } from "react";
import SearchForm, { type SearchFormValues } from "@/components/SearchForm";
import ResultsTable from "@/components/ResultsTable";
import type { AwardResult } from "@/lib/seats-aero";

export default function Home() {
  const [results, setResults] = useState<AwardResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  async function handleSearch(values: SearchFormValues) {
    setLoading(true);
    setError(null);
    setResults(null);

    const params = new URLSearchParams({
      origin: values.origin,
      destination: values.destination,
      startDate: values.startDate,
      endDate: values.endDate,
      cabin: values.cabin,
      sources: values.sources.join(","),
      onlyDirect: values.onlyDirect ? "true" : "false",
    });
    if (values.maxMiles) params.set("maxMiles", values.maxMiles);

    setQuery(
      `${values.origin} → ${values.destination}, ${values.startDate} to ${values.endDate}, ${values.cabin}`,
    );

    try {
      const res = await fetch(`/api/search/award?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || "Search failed");
      } else {
        setResults(data.results);
      }
    } catch {
      setError("Network error — please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">AwardTravel</h1>
            <p className="text-sm text-gray-500">
              Find cheap points &amp; miles flights
            </p>
          </div>
          <nav className="flex gap-4 text-sm">
            <span className="text-blue-600 font-medium">Search</span>
            <span className="text-gray-400">Alerts</span>
            <span className="text-gray-400">Account</span>
          </nav>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-8">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">
            Award Flight Search
          </h2>
          <SearchForm onSearch={handleSearch} loading={loading} />
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-8">
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {results && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
            <ResultsTable results={results} query={query} />
          </div>
        )}
      </main>
    </div>
  );
}
