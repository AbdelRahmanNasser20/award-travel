"use client";

import { useState, type FormEvent } from "react";

const PROGRAMS = [
  { id: "united", label: "United" },
  { id: "american", label: "American" },
  { id: "delta", label: "Delta" },
  { id: "jetblue", label: "JetBlue" },
  { id: "southwest", label: "Southwest" },
  { id: "aeroplan", label: "Aeroplan" },
  { id: "flyingblue", label: "Flying Blue" },
  { id: "velocity", label: "Velocity" },
  { id: "frontier", label: "Frontier" },
];

export interface SearchFormValues {
  origin: string;
  destination: string;
  startDate: string;
  endDate: string;
  cabin: string;
  sources: string[];
  maxMiles: string;
  onlyDirect: boolean;
}

export default function SearchForm({
  onSearch,
  loading,
}: {
  onSearch: (values: SearchFormValues) => void;
  loading: boolean;
}) {
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [cabin, setCabin] = useState("economy");
  const [sources, setSources] = useState<string[]>([
    "united",
    "american",
    "delta",
    "jetblue",
    "southwest",
  ]);
  const [maxMiles, setMaxMiles] = useState("");
  const [onlyDirect, setOnlyDirect] = useState(false);

  function toggleSource(id: string) {
    setSources((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id],
    );
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSearch({
      origin: origin.toUpperCase().trim(),
      destination: destination.toUpperCase().trim(),
      startDate,
      endDate,
      cabin,
      sources,
      maxMiles,
      onlyDirect,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Origin
          </label>
          <input
            type="text"
            required
            placeholder="JFK,LGA,EWR"
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
          <p className="text-xs text-gray-500 mt-1">
            Comma-separate for metro areas
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Destination
          </label>
          <input
            type="text"
            required
            placeholder="PHX"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Start Date
          </label>
          <input
            type="date"
            required
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            End Date
          </label>
          <input
            type="date"
            required
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Cabin
          </label>
          <select
            value={cabin}
            onChange={(e) => setCabin(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          >
            <option value="economy">Economy</option>
            <option value="premium">Premium Economy</option>
            <option value="business">Business</option>
            <option value="first">First</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Max Miles (budget)
          </label>
          <input
            type="number"
            placeholder="e.g. 17000"
            value={maxMiles}
            onChange={(e) => setMaxMiles(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div className="flex items-end pb-1">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={onlyDirect}
              onChange={(e) => setOnlyDirect(e.target.checked)}
              className="rounded border-gray-300"
            />
            Direct flights only
          </label>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Programs
        </label>
        <div className="flex flex-wrap gap-2">
          {PROGRAMS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => toggleSource(p.id)}
              className={`px-3 py-1 rounded-full text-sm border transition-colors ${
                sources.includes(p.id)
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-gray-600 border-gray-300 hover:border-gray-400"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <button
        type="submit"
        disabled={loading}
        className="w-full bg-blue-600 text-white py-3 px-4 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? "Searching..." : "Search Award Flights"}
      </button>
    </form>
  );
}
