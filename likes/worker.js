// The service behind blip.ivwi.fr, on Cloudflare Workers with a D1 database:
// likes, and voices shared from the site by people with no GitHub account.
//
//   GET    /likes             every voice's count, and the ones this person likes
//   POST   /likes/<voice>     like a voice
//   DELETE /likes/<voice>     take the like back
//
//   POST   /voices            share a voice: { name, theme, description,
//                             author, rules, wav } (wav: the site's .wav, base64)
//   GET    /voices/<id>       how far it is: queued, checking, publishing,
//                             live, or refused with the reason
//   POST   /voices/remove     { name, key }: remove a voice shared from here,
//                             with the key its sharing answered
//
// and, for the site-voice workflow of the voices repository only (it shows a
// token GitHub signs for it, OIDC):
//
//   GET    /voices/<id>/submission   the submission, which is then "checking"
//   POST   /voices/<id>/status       { status, reason, name, version }
//
// A person is known by a salted hash of their address (the SALT secret), never
// by the address itself. Only voices the catalog lists can be liked, ten a
// minute at most. A like is kept under the voice's name and version, so a new
// voice taking a removed voice's name starts from zero.
//
// Sharing starts the repository's site-voice workflow with the GITHUB_TOKEN
// secret: a fine-grained token for DoubleV840/blip-voices with only
// Actions: read and write. Three voices a day per person, thirty for everyone.

const ORIGINS = ['https://blip.ivwi.fr', 'http://localhost:8765']
const REPO = 'DoubleV840/blip-voices'
const CATALOG = `https://raw.githubusercontent.com/${REPO}/main/catalog.json`
const API = `https://api.github.com/repos/${REPO}`
const NAME = /^[a-z0-9][a-z0-9-]{1,19}$/
const MAX_PER_MINUTE = 10

// What add_voice.py takes; it checks everything again, words included.
const THEMES = ['retro', 'cute', 'soft', 'machine', 'creature', 'dark', 'weird']
const RESERVED = new Set(['classic', 'nes', 'soft', 'bubble', 'typewriter', 'robot', 'deep', 'chirp', 'critter', 'custom', 'on', 'off'])
const AUTHOR = /^[\p{L}\p{N}][\p{L}\p{N} .'-]{0,23}$/u
const RATE = 22050
const MAX_WAV = 44 + 2 * RATE * 2 // the site sends a sound's first 2 s
const SHARES_PER_DAY = 3
const SHARES_PER_HOUR = 8 // refused ones too
const SHARES_PER_DAY_FOR_ALL = 30
const DAY = 24 * 3600_000
// Under way: a submission no workflow has finished, younger than this.
const UNDER_WAY = ['queued', 'checking', 'publishing']
const STALE = 15 * 60_000

// The workflow's token: who signs it, for whom, from which workflow. Local
// tests point OIDC_JWKS and GITHUB_API (vars) at a stand-in for GitHub.
const ISSUER = 'https://token.actions.githubusercontent.com'
const AUDIENCE = 'blip-likes'
const WORKFLOW = `${REPO}/.github/workflows/site-voice.yml@refs/heads/main`

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') ?? ''
    const headers = {
      'Access-Control-Allow-Origin': ORIGINS.includes(origin) ? origin : ORIGINS[0],
      'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Cache-Control': 'no-store',
      'Content-Type': 'application/json',
      Vary: 'Origin',
    }
    const answer = (body, status = 200) => new Response(JSON.stringify(body), { status, headers })
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers })

    try {
      const person = await personOf(request, env)
      const path = new URL(request.url).pathname

      if (path === '/voices' && request.method === 'POST') return await share(request, env, person, answer)
      if (path === '/voices/remove' && request.method === 'POST') return await removeOwn(request, env, answer)
      const voice = path.match(/^\/voices\/([0-9a-f-]{36})(\/submission|\/status)?$/)
      if (voice) {
        const [, id, part] = voice
        if (!part && request.method === 'GET') return await progress(env, id, answer)
        if (!(await isWorkflow(request, env))) return answer({ error: 'only the site-voice workflow can' }, 403)
        if (part === '/submission' && request.method === 'GET') return await submission(env, id, answer)
        if (part === '/status' && request.method === 'POST') return await report(request, env, id, answer)
        return answer({ error: 'not found' }, 404)
      }

      if (path === '/likes' && request.method === 'GET') {
        const voices = await catalog()
        const counts = await env.DB.prepare('SELECT voice, COUNT(*) AS n FROM likes GROUP BY voice').all()
        const mine = await env.DB.prepare('SELECT voice FROM likes WHERE voter = ?').bind(person).all()
        const countOf = new Map(counts.results.map(row => [row.voice, row.n]))
        const isMine = new Set(mine.results.map(row => row.voice))
        return answer({
          counts: Object.fromEntries(voices.filter(v => countOf.has(keyOf(v))).map(v => [v.name, countOf.get(keyOf(v))])),
          liked: voices.filter(v => isMine.has(keyOf(v))).map(v => v.name),
        })
      }

      const name = path.match(/^\/likes\/([^/]+)$/)?.[1]
      if (name === undefined || !['POST', 'DELETE'].includes(request.method)) return answer({ error: 'not found' }, 404)
      const listed = NAME.test(name) ? (await catalog()).find(v => v.name === name) : undefined
      if (listed === undefined) return answer({ error: 'no such voice' }, 404)
      const liked = keyOf(listed)

      if (request.method === 'POST') {
        const since = Date.now() - 60_000
        const recent = await env.DB.prepare('SELECT COUNT(*) AS n FROM likes WHERE voter = ? AND at > ?').bind(person, since).first()
        if (recent.n >= MAX_PER_MINUTE) return answer({ error: 'too many likes, try again in a minute' }, 429)
        await env.DB.prepare('INSERT OR IGNORE INTO likes (voice, voter, at) VALUES (?, ?, ?)').bind(liked, person, Date.now()).run()
      } else {
        await env.DB.prepare('DELETE FROM likes WHERE voice = ? AND voter = ?').bind(liked, person).run()
      }

      const total = await env.DB.prepare('SELECT COUNT(*) AS n FROM likes WHERE voice = ?').bind(liked).first()
      return answer({ voice: name, count: total.n, liked: request.method === 'POST' })
    } catch {
      return answer({ error: 'something went wrong' }, 500)
    }
  },
}

// ---- Sharing a voice ------------------------------------------------------

// Checks what it can at once (add_voice.py checks it all again), keeps it,
// and starts the workflow that publishes it.
async function share(request, env, person, answer) {
  const refuse = (error, field, status = 400) => answer({ error, field }, status)
  const text = await request.text()
  if (text.length > 200_000) return refuse('That is a lot for one short sound.', 'sound', 413)
  let body
  try {
    body = JSON.parse(text)
  } catch {
    return refuse('Send the voice as JSON.')
  }

  const name = String(body.name ?? '').trim().toLowerCase().replace(/[\s_]+/g, '-').replace(/^-+|-+$/g, '')
  const theme = String(body.theme ?? '').trim().toLowerCase()
  const description = String(body.description ?? '').split(/\s+/).filter(Boolean).join(' ')
  const author = String(body.author ?? '').split(/\s+/).filter(Boolean).join(' ')
  if (!NAME.test(name)) return refuse('The name takes 2 to 20 letters, digits or dashes, like cat-meow.', 'name')
  if (!THEMES.includes(theme)) return refuse(`The theme is one of ${THEMES.join(', ')}.`, 'theme')
  if (description.length < 1 || description.length > 60) return refuse('The description takes 1 to 60 characters.', 'description')
  if (author && !AUTHOR.test(author)) return refuse('Your name takes 1 to 24 letters, digits, spaces, dots or dashes.', 'author')
  if (body.rules !== true) return refuse('Tick the box: the sound is yours to share.', 'rules')
  const wav = typeof body.wav === 'string' && body.wav.length <= Math.ceil(MAX_WAV / 3) * 4 ? bytesOf(body.wav) : null
  if (!wav || !isSiteWav(wav)) return refuse('The sound is not the .wav this site makes: drop it again.', 'sound')

  if (RESERVED.has(name) || (await catalog(env, true)).some(v => v.name === name)) {
    return refuse(`There is already a voice named ${name}: pick another name.`, 'name', 409)
  }
  const now = Date.now()
  const taken = await env.DB.prepare(
    `SELECT 1 FROM submissions WHERE name = ? AND at > ? AND status IN ('queued', 'checking', 'publishing', 'live')`,
  ).bind(name, now - STALE).first()
  if (taken) return refuse(`Someone just shared a voice named ${name}: pick another name.`, 'name', 409)

  const counts = await env.DB.prepare(
    `SELECT
       SUM(sharer = ?1 AND at > ?2 AND status NOT IN ('refused', 'failed')) AS today,
       SUM(sharer = ?1 AND at > ?3) AS hour,
       SUM(at > ?2 AND status != 'failed') AS everyone
     FROM submissions WHERE at > ?2`,
  ).bind(person, now - DAY, now - 3600_000).first()
  if ((counts.today ?? 0) >= SHARES_PER_DAY) return refuse(`${SHARES_PER_DAY} voices a day at most: this one is welcome tomorrow.`, null, 429)
  if ((counts.hour ?? 0) >= SHARES_PER_HOUR) return refuse('Easy there! Try again in an hour.', null, 429)
  if ((counts.everyone ?? 0) >= SHARES_PER_DAY_FOR_ALL) return refuse('Lots of voices shared today already: try again tomorrow.', null, 429)

  const id = crypto.randomUUID()
  const key = hex(crypto.getRandomValues(new Uint8Array(16)))
  await env.DB.prepare(
    `INSERT INTO submissions (id, name, theme, description, author, wav, sharer, at, status, key)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)`,
  ).bind(id, name, theme, description, author, body.wav, person, now, await sha256(key)).run()

  const started = await dispatch(env, 'site-voice.yml', { id })
  if (!started) {
    await env.DB.prepare(`UPDATE submissions SET status = 'failed', wav = NULL, reason = ? WHERE id = ?`)
      .bind('the site could not start the check', id).run()
    return refuse('The site can’t share voices right now: try again later, or use the GitHub form.', null, 503)
  }
  return answer({ id, key, name, status: 'queued' }, 202)
}

async function progress(env, id, answer) {
  const row = await env.DB.prepare('SELECT name, status, reason, version, at FROM submissions WHERE id = ?').bind(id).first()
  if (!row) return answer({ error: 'no such submission' }, 404)
  return answer({ name: row.name, status: row.status, reason: row.reason ?? undefined, version: row.version ?? undefined, at: row.at })
}

async function submission(env, id, answer) {
  const row = await env.DB.prepare('SELECT * FROM submissions WHERE id = ?').bind(id).first()
  if (!row || !row.wav || !['queued', 'checking'].includes(row.status)) return answer({ error: 'nothing to check' }, 404)
  await env.DB.prepare(`UPDATE submissions SET status = 'checking' WHERE id = ?`).bind(id).run()
  const { name, theme, description, author, wav } = row
  return answer({ name, theme, description, author, wav })
}

async function report(request, env, id, answer) {
  const { status, reason = '', name = '', version = '' } = await request.json()
  if (!['publishing', 'live', 'refused'].includes(status)) return answer({ error: 'no such status' }, 400)
  const isDone = status !== 'publishing'
  const row = await env.DB.prepare('SELECT name FROM submissions WHERE id = ?').bind(id).first()
  if (!row) return answer({ error: 'no such submission' }, 404)
  await env.DB.prepare(
    `UPDATE submissions SET status = ?, reason = ?, version = ?, name = ?${isDone ? ', wav = NULL' : ''} WHERE id = ?`,
  ).bind(
    status,
    String(reason).slice(0, 300) || null,
    /^[0-9a-f]{12}$/.test(version) ? version : null,
    status === 'live' && NAME.test(name) ? name : row.name,
    id,
  ).run()
  return answer({ ok: true })
}

// Removes a voice its sharer shared from the site: the key it was given
// matches, and the catalog still lists that very voice (not a newer one that
// took its name since).
async function removeOwn(request, env, answer) {
  const { name = '', key = '' } = await request.json().catch(() => ({}))
  if (!NAME.test(name) || !/^[0-9a-f]{32}$/.test(key)) return answer({ error: 'Which voice?' }, 400)
  const row = await env.DB.prepare(`SELECT id, version FROM submissions WHERE name = ? AND key = ? AND status = 'live'`)
    .bind(name, await sha256(key)).first()
  if (!row) return answer({ error: 'This browser didn’t share that voice.' }, 403)
  const listed = (await catalog(env, true)).find(v => v.name === name)
  if (!listed || listed.version !== row.version) return answer({ error: 'It’s gone already.' }, 404)
  if (!(await dispatch(env, 'remove-voice.yml', { name }))) return answer({ error: 'Couldn’t remove it right now: try again later.' }, 503)
  await env.DB.prepare(`UPDATE submissions SET status = 'removed' WHERE id = ?`).bind(row.id).run()
  return answer({ ok: true })
}

// Starts one of the repository's workflows; false when GitHub says no.
async function dispatch(env, workflow, inputs) {
  if (!env.GITHUB_TOKEN) return false
  const response = await fetch(`${env.GITHUB_API ?? API}/actions/workflows/${workflow}/dispatches`, {
    method: 'POST',
    headers: github(env),
    body: JSON.stringify({ ref: 'main', inputs }),
  })
  return response.ok
}

const github = env => ({
  Accept: 'application/vnd.github+json',
  Authorization: `Bearer ${env.GITHUB_TOKEN}`,
  'User-Agent': 'blip-likes',
  'X-GitHub-Api-Version': '2022-11-28',
})

// The .wav the site makes: mono, 16-bit PCM at RATE, 2 s at most.
function isSiteWav(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const word = at => String.fromCharCode(...bytes.subarray(at, at + 4))
  return (
    bytes.length > 44 && bytes.length <= MAX_WAV && bytes.length % 2 === 0 &&
    word(0) === 'RIFF' && word(8) === 'WAVE' && word(12) === 'fmt ' && word(36) === 'data' &&
    view.getUint32(16, true) === 16 && view.getUint16(20, true) === 1 && view.getUint16(22, true) === 1 &&
    view.getUint32(24, true) === RATE && view.getUint16(34, true) === 16 &&
    view.getUint32(40, true) === bytes.length - 44
  )
}

function bytesOf(base64) {
  try {
    return Uint8Array.from(atob(base64), c => c.charCodeAt(0))
  } catch {
    return null
  }
}

// ---- The workflow's token -------------------------------------------------

// Whether the request shows a token GitHub signed for the site-voice workflow
// of the voices repository, on main, still valid.
async function isWorkflow(request, env) {
  const token = request.headers.get('Authorization')?.match(/^Bearer ([\w-]+\.[\w-]+\.[\w-]+)$/)?.[1]
  if (!token) return false
  try {
    const [head, body, signature] = token.split('.')
    const header = JSON.parse(textOf(head))
    const claims = JSON.parse(textOf(body))
    if (header.alg !== 'RS256') return false
    const jwks = await fetch(env.OIDC_JWKS ?? `${ISSUER}/.well-known/jwks`, { cf: { cacheTtl: 3600, cacheEverything: true } })
    const jwk = (await jwks.json()).keys.find(k => k.kid === header.kid)
    if (!jwk) return false
    const algorithm = { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }
    const key = await crypto.subtle.importKey('jwk', { kty: jwk.kty, n: jwk.n, e: jwk.e }, algorithm, false, ['verify'])
    const isSigned = await crypto.subtle.verify(algorithm, key, base64url(signature), new TextEncoder().encode(`${head}.${body}`))
    const now = Date.now() / 1000
    return (
      isSigned &&
      claims.iss === ISSUER &&
      [claims.aud].flat().includes(AUDIENCE) &&
      claims.repository?.toLowerCase() === REPO.toLowerCase() &&
      claims.workflow_ref?.toLowerCase() === WORKFLOW.toLowerCase() &&
      claims.exp > now &&
      (claims.nbf ?? 0) <= now + 60
    )
  } catch {
    return false
  }
}

const base64url = text => Uint8Array.from(atob(text.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
const textOf = text => new TextDecoder().decode(base64url(text))

// ---- Shared -----------------------------------------------------------------

async function personOf(request, env) {
  const address = request.headers.get('CF-Connecting-IP') ?? 'local'
  return sha256(`${env.SALT ?? ''}:${address}`)
}

async function sha256(text) {
  return hex(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))))
}

const hex = bytes => [...bytes].map(b => b.toString(16).padStart(2, '0')).join('')

// The voices the catalog lists; Cloudflare keeps the raw file a minute, and
// GitHub's CDN up to five. Fresh, it comes from the API (the token's reads)
// before the raw file.
async function catalog(env, isFresh = false) {
  if (isFresh && env.GITHUB_TOKEN) {
    try {
      const response = await fetch(`${env.GITHUB_API ?? API}/contents/catalog.json`, { headers: { ...github(env), Accept: 'application/vnd.github.raw' } })
      if (response.ok) return (await response.json()).voices ?? []
    } catch {
      // The raw file, then.
    }
  }
  const response = await fetch(CATALOG, { cf: { cacheTtl: 60, cacheEverything: true } })
  if (!response.ok) throw new Error(`the catalog answered ${response.status}`)
  const { voices = [] } = await response.json()
  return voices
}

// Where a voice's likes are kept: its name, and its version when it has one.
const keyOf = voice => (voice.version ? `${voice.name}:${voice.version}` : voice.name)
