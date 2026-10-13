// Emitted series id → overlay id, read by the crosshair callback to label values. Entries leave
// with their overlays and with the chart (Mission 5 review minor, plan P14 item 8), so a removed
// indicator cannot resurface under a stale id and a rebuilt chart starts clean.
export class SeriesMap {
  private readonly map = new Map<string, string>();

  set(seriesId: string, overlayId: string): void {
    this.map.set(seriesId, overlayId);
  }

  overlayOf(seriesId: string): string | undefined {
    return this.map.get(seriesId);
  }

  /** Drop every series that belongs to one of these overlays. */
  forget(overlayIds: Iterable<string>): void {
    const gone = new Set(overlayIds);
    for (const [seriesId, overlayId] of this.map) if (gone.has(overlayId)) this.map.delete(seriesId);
  }

  clear(): void {
    this.map.clear();
  }

  get size(): number {
    return this.map.size;
  }
}
