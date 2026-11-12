// Likes for blip.ivwi.fr, on Cloudflare Workers with a D1 database.
//
//   GET    /likes          every voice's count, and the ones this person likes
//   POST   /likes/<voice>  like a voice
//   DELETE /likes/<voice>  take the like back
//
// One like per voice and person. A person is known by a salted hash of their
// address (the SALT secret), never by the address itself. Only voices the
// catalog lists can be liked, and a person likes ten voices a minute at most.

const ORIGINS = ['https://blip.ivwi.fr', 'http://localhost:8765']
const CATALOG = 'https://raw.githubusercontent.com/DoubleV840/blip-voices/main/catalog.json'
const NAME = /^[a-z0-9][a-z0-9-]{1,19}$/
const MAX_PER_MINUTE = 10

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') ?? ''
    const headers = {
      'Access-Control-Allow-Origin': ORIGINS.includes(origin) ? origin : ORIGINS[0],
      'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
      'Cache-Control': 'no-store',
      'Content-Type': 'application/json',
      Vary: 'Origin',
    }
    const answer = (body, status = 200) => new Response(JSON.stringify(body), { status, headers })
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers })

    try {
      const voter = await voterOf(request, env)
      const path = new URL(request.url).pathname

      if (path === '/likes' && request.method === 'GET') {
        const counts = await env.DB.prepare('SELECT voice, COUNT(*) AS n FROM likes GROUP BY voice').all()
        const mine = await env.DB.prepare('SELECT voice FROM likes WHERE voter = ?').bind(voter).all()
        return answer({
          counts: Object.fromEntries(counts.results.map(row => [row.voice, row.n])),
          liked: mine.results.map(row => row.voice),
        })
      }

      const voice = path.match(/^\/likes\/([^/]+)$/)?.[1]
      if (voice === undefined || !['POST', 'DELETE'].includes(request.method)) return answer({ error: 'not found' }, 404)
      if (!NAME.test(voice) || !(await isListed(voice))) return answer({ error: 'no such voice' }, 404)

      if (request.method === 'POST') {
        const since = Date.now() - 60_000
        const recent = await env.DB.prepare('SELECT COUNT(*) AS n FROM likes WHERE voter = ? AND at > ?').bind(voter, since).first()
        if (recent.n >= MAX_PER_MINUTE) return answer({ error: 'too many likes, try again in a minute' }, 429)
        await env.DB.prepare('INSERT OR IGNORE INTO likes (voice, voter, at) VALUES (?, ?, ?)').bind(voice, voter, Date.now()).run()
      } else {
        await env.DB.prepare('DELETE FROM likes WHERE voice = ? AND voter = ?').bind(voice, voter).run()
      }

      const total = await env.DB.prepare('SELECT COUNT(*) AS n FROM likes WHERE voice = ?').bind(voice).first()
      return answer({ voice, count: total.n, liked: request.method === 'POST' })
    } catch {
      return answer({ error: 'something went wrong' }, 500)
    }
  },
}

async function voterOf(request, env) {
  const address = request.headers.get('CF-Connecting-IP') ?? 'local'
  const bytes = new TextEncoder().encode(`${env.SALT ?? ''}:${address}`)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('')
}

// Whether the catalog lists the voice; Cloudflare keeps the catalog a minute.
async function isListed(voice) {
  const response = await fetch(CATALOG, { cf: { cacheTtl: 60, cacheEverything: true } })
  if (!response.ok) return false
  const { voices = [] } = await response.json()
  return voices.some(v => v.name === voice)
}
