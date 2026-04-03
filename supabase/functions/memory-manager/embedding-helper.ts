/**
 * Embedding Helper fuer Memory Manager
 *
 * Erzeugt Embeddings via OpenAI text-embedding-3-small.
 * Wird NUR aufgerufen wenn OPENAI_API_KEY als Env-Variable gesetzt ist.
 * Ohne Key funktioniert alles weiter wie bisher (ILIKE-Suche).
 *
 * Kosten: ~$0.02 pro 1M Tokens = praktisch kostenlos bei normaler Nutzung
 *
 * Eingebunden in index.ts:
 * - handlePost: Embedding nach Insert/Update generieren
 * - handleSearch: ?semantic=true fuer Vector Search
 * - backfill_embeddings: Bestehende Eintraege nachtraeglich mit Embeddings versehen
 */

const OPENAI_API_KEY = Deno.env.get('OPENAI_API_KEY')
const EMBEDDING_MODEL = 'text-embedding-3-small'
const EMBEDDING_DIMENSIONS = 1536

/**
 * Erzeugt ein Embedding fuer den gegebenen Text.
 * Gibt null zurueck wenn kein API Key oder ein Fehler auftritt.
 * Faellt NIEMALS mit einer Exception -- always graceful degradation.
 */
export async function generateEmbedding(text: string): Promise<number[] | null> {
  if (!OPENAI_API_KEY) {
    return null
  }

  if (!text || text.trim().length === 0) {
    return null
  }

  // Text auf 8000 Tokens begrenzen (grobe Schaetzung: 4 chars = 1 Token)
  const truncated = text.slice(0, 32000)

  try {
    const response = await fetch('https://api.openai.com/v1/embeddings', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${OPENAI_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: EMBEDDING_MODEL,
        input: truncated,
        dimensions: EMBEDDING_DIMENSIONS,
      }),
    })

    if (!response.ok) {
      console.error(`Embedding API error: ${response.status} ${response.statusText}`)
      return null
    }

    const result = await response.json()
    return result.data?.[0]?.embedding || null
  } catch (error) {
    console.error('Embedding generation failed:', error)
    return null
  }
}

/**
 * Backfill: Erzeugt Embeddings fuer bestehende Eintraege ohne Embedding.
 * Aufruf: POST /memory-manager?action=backfill_embeddings&layer=core
 * Verarbeitet max 50 Eintraege pro Aufruf (Rate Limit Schutz).
 */
export async function backfillEmbeddings(
  supabase: any,
  layer: 'core' | 'active'
): Promise<{ processed: number; errors: number }> {
  const table = layer === 'core' ? 'memory_core' : 'memory_active'

  const { data: entries, error } = await supabase
    .from(table)
    .select('id, title, content')
    .is('embedding', null)
    .limit(50)

  if (error) {
    return { processed: 0, errors: 1 }
  }
  if (!entries || entries.length === 0) {
    return { processed: 0, errors: 0 }
  }

  let processed = 0
  let errors = 0

  for (const entry of entries) {
    const embedding = await generateEmbedding(`${entry.title} ${entry.content}`)
    if (embedding) {
      const { error: updateError } = await supabase
        .from(table)
        .update({ embedding })
        .eq('id', entry.id)

      if (updateError) {
        errors++
      } else {
        processed++
      }
    } else {
      errors++
    }

    // Rate limiting: 100ms zwischen Requests
    await new Promise(resolve => setTimeout(resolve, 100))
  }

  return { processed, errors }
}
