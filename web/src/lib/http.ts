export async function fetchJson(
	url: string,
	signal?: AbortSignal,
): Promise<unknown> {
	const response = await fetch(url, { signal });
	if (!response.ok)
		throw new Error(`Failed to load ${url}: ${response.status}`);
	return response.json();
}
