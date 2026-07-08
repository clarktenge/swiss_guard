import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

/** True when both env vars are present, so the UI can show a helpful hint. */
export const isSupabaseConfigured = Boolean(url && anonKey)

// createClient() throws on an empty URL, which would white-screen the whole app
// before the "not configured" banner can render. Fall back to a syntactically
// valid placeholder when env is unset — the hook never issues a query unless
// isSupabaseConfigured is true, so the placeholder is never actually contacted.
const PLACEHOLDER_URL = 'https://placeholder.supabase.co'
const PLACEHOLDER_KEY = 'placeholder-anon-key'

/**
 * Read-only Supabase client for the dashboard.
 *
 * Uses the ANON key, never the service role key. What this client can see is
 * governed by the public-read RLS policies in db/migration_007.sql — the anon
 * key is safe to ship in a Vite build for that reason.
 */
export const supabase = createClient(
  url || PLACEHOLDER_URL,
  anonKey || PLACEHOLDER_KEY,
)
