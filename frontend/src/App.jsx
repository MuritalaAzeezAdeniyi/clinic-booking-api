import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const apiBase = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
const apiKey = import.meta.env.VITE_API_KEY || ''

function formatLocalDateTime(value) {
  if (!value) return '—'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value

  return date.toLocaleString([], {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

async function requestJson(path, options = {}) {
  const headers = {
    'X-API-Key': apiKey,
    ...(options.headers || {}),
  }

  if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }

  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers,
  })

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '')

  if (!response.ok) {
    const errorMessage =
      (payload && typeof payload === 'object' && payload.error) ||
      (typeof payload === 'string' && payload) ||
      response.statusText ||
      'Request failed'

    const error = new Error(errorMessage)
    error.status = response.status
    error.retryAfter = response.headers.get('Retry-After')
    throw error
  }

  return payload
}

export default function App() {
  const [slots, setSlots] = useState([])
  const [providerFilter, setProviderFilter] = useState('all')
  const [selectedSlotId, setSelectedSlotId] = useState('')
  const [formData, setFormData] = useState({ name: '', email: '' })
  const [slotsLoading, setSlotsLoading] = useState(true)
  const [slotsError, setSlotsError] = useState('')
  const [bookingLoading, setBookingLoading] = useState(false)
  const [cancelLoading, setCancelLoading] = useState(false)
  const [message, setMessage] = useState({ type: '', text: '' })
  const [confirmation, setConfirmation] = useState(null)
  const [lookupEmail, setLookupEmail] = useState('')
  const [lookupBookings, setLookupBookings] = useState([])
  const [lookupCursor, setLookupCursor] = useState(null)
  const [lookupLoading, setLookupLoading] = useState(false)
  const [lookupError, setLookupError] = useState('')
  const [lookupSearched, setLookupSearched] = useState(false)
  const bookingAttemptRef = useRef(null)

  const providerOptions = useMemo(
    () => ['all', ...new Set(slots.map((slot) => slot.provider))],
    [slots],
  )

  const selectedSlot = slots.find((slot) => slot.id === selectedSlotId) || null

  const loadSlots = useCallback(async () => {
    setSlotsLoading(true)
    setSlotsError('')

    try {
      const query = providerFilter !== 'all' ? `?provider=${encodeURIComponent(providerFilter)}` : ''
      const data = await requestJson(`/slots${query}`)
      const nextSlots = Array.isArray(data.slots) ? data.slots : []
      setSlots(nextSlots)

      if (!nextSlots.some((slot) => slot.id === selectedSlotId)) {
        const preferred = nextSlots.find((slot) => slot.available)
        setSelectedSlotId(preferred ? preferred.id : nextSlots[0]?.id || '')
      }
    } catch (error) {
      setSlotsError(error.message || 'Unable to load slots right now.')
    } finally {
      setSlotsLoading(false)
    }
  }, [providerFilter, selectedSlotId])

  useEffect(() => {
    loadSlots()
  }, [loadSlots])

  const handleBookingSubmit = async (event) => {
    event.preventDefault()

    if (!selectedSlot) {
      setMessage({ type: 'error', text: 'Please choose an available slot.' })
      return
    }

    const bookingPayload = {
      slot_id: selectedSlot.id,
      name: formData.name,
      email: formData.email,
    }
    const attemptFingerprint = JSON.stringify(bookingPayload)
    if (bookingAttemptRef.current?.fingerprint !== attemptFingerprint) {
      bookingAttemptRef.current = {
        fingerprint: attemptFingerprint,
        key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      }
    }

    setBookingLoading(true)
    setMessage({ type: '', text: '' })

    try {
      const booking = await requestJson('/bookings', {
        method: 'POST',
        headers: { 'Idempotency-Key': bookingAttemptRef.current.key },
        body: JSON.stringify(bookingPayload),
      })

      setConfirmation({
        ...booking,
        slot: selectedSlot,
      })
      setFormData({ name: '', email: '' })
      setMessage({
        type: 'success',
        text: `Booking confirmed for ${booking.name} at ${formatLocalDateTime(selectedSlot.start)}.`,
      })
      await loadSlots()
    } catch (error) {
      const errorText = error.status === 429
        ? `Too many booking attempts. Please wait ${error.retryAfter || 'at least 1'} seconds before trying again. ${error.message}`
        : error.message || 'Booking failed.'
      setMessage({ type: 'error', text: errorText })
    } finally {
      setBookingLoading(false)
    }
  }

  const lookupMyBookings = async (event, cursor = null, replace = true) => {
    event?.preventDefault()
    if (!lookupEmail.trim()) {
      setLookupError('Enter your email address to look up bookings.')
      return
    }

    setLookupLoading(true)
    setLookupError('')
    try {
      const query = new URLSearchParams({ email: lookupEmail.trim() })
      if (cursor) query.set('cursor', cursor)
      const result = await requestJson(`/bookings?${query.toString()}`)
      setLookupBookings((current) => replace ? result.bookings : [...current, ...result.bookings])
      setLookupCursor(result.next_cursor)
      setLookupSearched(true)
    } catch (error) {
      setLookupError(error.message || 'Unable to look up bookings.')
    } finally {
      setLookupLoading(false)
    }
  }

  const handleCancelBooking = async () => {
    if (!confirmation?.id) return

    setCancelLoading(true)
    setMessage({ type: '', text: '' })

    try {
      const cancelledBooking = await requestJson(`/bookings/${confirmation.id}`, {
        method: 'DELETE',
      })

      setConfirmation((current) => ({
        ...(current || {}),
        ...cancelledBooking,
        slot: current?.slot || null,
      }))
      setMessage({
        type: 'success',
        text: 'Booking cancelled successfully.',
      })
      await loadSlots()
    } catch (error) {
      setMessage({ type: 'error', text: error.message || 'Unable to cancel this booking.' })
    } finally {
      setCancelLoading(false)
    }
  }

  return (
    <main className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="Slotwell home">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 40 40" role="img">
              <rect x="1" y="1" width="38" height="38" rx="13" fill="currentColor" />
              <path d="M20 10v20M10 20h20" stroke="white" strokeWidth="3.5" strokeLinecap="round" />
              <circle cx="29" cy="11" r="3" fill="#a7f3d0" />
            </svg>
          </span>
          <span className="brand-copy"><strong>Slotwell</strong><small>Care, made simple</small></span>
        </a>
        <span className="header-note"><span className="header-dot" /> A little more time for you</span>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Thoughtful care starts here</p>
          <h1>Book your care,<br /><span>on your time.</span></h1>
          <p className="hero-description">Choose a time that works for you. We’ll take care of the rest.</p>
        </div>
        {!apiKey && (
          <div className="env-warning">
            Set VITE_API_KEY in frontend/.env before using the app.
          </div>
        )}
        <div className="hero-art" aria-hidden="true">
          <div className="hero-orbit orbit-one" />
          <div className="hero-orbit orbit-two" />
          <div className="hero-cross">+</div>
          <div className="hero-note"><span className="note-check">✓</span><span><strong>Your time matters</strong><small>Care on your schedule</small></span></div>
        </div>
      </section>

      <div className="booking-layout">
        <section className="panel slots-panel">
          <div className="panel-heading">
            <div>
              <p className="section-kicker">FIND YOUR MOMENT</p>
              <h2>Available slots</h2>
              <p className="panel-subtitle">Pick a time that feels right.</p>
            </div>
            <label className="provider-filter">
              <span>Choose a provider</span>
              <select value={providerFilter} onChange={(event) => setProviderFilter(event.target.value)}>
                {providerOptions.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider === 'all' ? 'All providers' : provider}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {slotsLoading ? (
            <div className="slots-grid" aria-label="Loading appointment slots">
              <p className="status-message info" aria-live="polite">Loading slots… the API may be waking up.</p>
              {[0, 1, 2, 3].map((item) => (
                <div className="slot-skeleton" key={item} aria-hidden="true">
                  <span className="skeleton-line skeleton-provider" />
                  <span className="skeleton-line skeleton-date" />
                  <span className="skeleton-line skeleton-time" />
                </div>
              ))}
            </div>
          ) : slotsError ? (
            <div className="status-message error" role="alert" aria-live="assertive"><span className="alert-icon" aria-hidden="true">!</span>{slotsError}</div>
          ) : (
            <div className="slots-grid">
              {slots.length === 0 ? (
                <p className="empty-state">No slots are available for this provider.</p>
              ) : (
                slots.map((slot, index) => {
                  const initials = slot.provider.split(/\s+/).filter(Boolean).map((part) => part[0]).slice(0, 2).join('').toUpperCase()
                  const slotStart = new Date(slot.start)
                  const slotEnd = new Date(slot.end)
                  const isPast = !Number.isFinite(slotStart.getTime()) || slotStart.getTime() <= Date.now()
                  const isAvailable = slot.available && !isPast
                  const dateLabel = Number.isNaN(slotStart.getTime()) ? slot.start : slotStart.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
                  const timeLabel = Number.isNaN(slotStart.getTime()) || Number.isNaN(slotEnd.getTime())
                    ? `${formatLocalDateTime(slot.start)} – ${formatLocalDateTime(slot.end)}`
                    : `${slotStart.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} – ${slotEnd.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`

                  return (
                    <article
                      key={slot.id}
                      style={{ '--card-order': index }}
                      className={`slot-card ${isAvailable ? 'available' : 'unavailable'} ${selectedSlotId === slot.id ? 'selected' : ''}`}
                    >
                      <div className="slot-card-top">
                        <span className="provider-avatar" aria-hidden="true">{initials}</span>
                        <span className={`availability ${isAvailable ? 'open' : 'closed'}`}>
                          <span className="availability-dot" />{isAvailable ? 'Available' : isPast ? 'Past' : 'Booked'}
                        </span>
                      </div>
                      <p className="slot-provider">{slot.provider}</p>
                      <p className="slot-date">{dateLabel}</p>
                      <p className="slot-times">{timeLabel}</p>
                      <button
                        type="button"
                        className="slot-select-button"
                        onClick={() => setSelectedSlotId(slot.id)}
                        disabled={!isAvailable}
                      >
                        {selectedSlotId === slot.id ? 'Selected' : isPast ? 'Time passed' : isAvailable ? 'Choose this time' : 'Not available'}
                        {isAvailable && <span aria-hidden="true">→</span>}
                      </button>
                    </article>
                  )
                })
              )}
            </div>
          )}
        </section>

        <aside className="side-column">
          <section className="panel booking-panel">
            <div className="form-heading">
              <span className="form-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="16" rx="3" /><path d="M8 3v4M16 3v4M4 10h16M8 14h3M8 17h6" /></svg>
              </span>
              <div><p className="section-kicker">NEXT STEP</p><h2>Book your visit</h2></div>
            </div>

            <form onSubmit={handleBookingSubmit} className="booking-form">
              <label>
                Selected appointment
                <input
                  type="text"
                  value={selectedSlot ? `${selectedSlot.provider} · ${formatLocalDateTime(selectedSlot.start)}` : 'Choose an available slot'}
                  readOnly
                />
                <small className="field-hint">Select a green appointment card to get started.</small>
              </label>

              <label>
                Full name
                <input
                  type="text"
                  placeholder="e.g. Aishat Sarafadeen"
                  value={formData.name}
                  onChange={(event) => setFormData((current) => ({ ...current, name: event.target.value }))}
                  required
                />
              </label>

              <label>
                Email address
                <input
                  type="email"
                  placeholder="you@example.com"
                  value={formData.email}
                  onChange={(event) => setFormData((current) => ({ ...current, email: event.target.value }))}
                  required
                />
                <small className="field-hint">Your confirmation will be associated with this email.</small>
              </label>

              <button type="submit" className="primary-button" disabled={bookingLoading || !selectedSlot || !selectedSlot.available}>
                {bookingLoading && <span className="button-spinner" aria-hidden="true" />}
                {bookingLoading ? 'Booking…' : 'Book appointment'}
                {!bookingLoading && <span aria-hidden="true">→</span>}
              </button>
              <p className="privacy-note"><span aria-hidden="true">✓</span> Your details are only used for this appointment.</p>
            </form>
          </section>

          <div className="care-note"><span className="care-note-mark" aria-hidden="true">✳</span><p><strong>A calmer way to book.</strong><br />Take a moment for yourself. We’ll be ready when you are.</p></div>
        </aside>
      </div>

      {message.text && (
        <div className={`status-message page-feedback ${message.type === 'success' ? 'success' : 'error'}`} role={message.type === 'error' ? 'alert' : 'status'} aria-live={message.type === 'error' ? 'assertive' : 'polite'}>
          <span className="alert-icon" aria-hidden="true">{message.type === 'success' ? '✓' : '!'}</span>{message.text}
        </div>
      )}

      {confirmation && (
        <section className="panel confirmation-panel" aria-live="polite">
          <div className="confirmation-heading">
            <span className="success-check" aria-hidden="true"><svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" /><path d="m9 16 5 5 9-10" /></svg></span>
            <div><p className="section-kicker">YOU’RE ALL SET</p><h2>Booking confirmed</h2></div>
          </div>
          <div className="confirmation-details">
            <p><span>Name</span><strong>{confirmation.name}</strong></p>
            <p><span>Email</span><strong>{confirmation.email}</strong></p>
            <p><span>Appointment</span><strong>{confirmation.slot?.provider || 'Clinic'} · {formatLocalDateTime(confirmation.slot?.start || confirmation.created_at)}</strong></p>
            <p><span>Status</span><strong className="confirmation-status">{confirmation.status}</strong></p>
            <p><span>Booking ID</span><strong className="booking-id">{confirmation.id}</strong></p>
          </div>

          <button type="button" className="danger-button" onClick={handleCancelBooking} disabled={cancelLoading}>
            {cancelLoading && <span className="button-spinner" aria-hidden="true" />}
            {cancelLoading ? 'Cancelling…' : 'Cancel booking'}
          </button>
        </section>
      )}

      <section className="panel lookup-panel">
        <div className="lookup-heading">
          <span className="lookup-icon" aria-hidden="true">⌕</span>
          <div><p className="section-kicker">ALREADY BOOKED?</p><h2>My bookings</h2></div>
        </div>
        <p className="panel-subtitle">Look up appointments linked to your email address.</p>
        <form className="lookup-form" onSubmit={(event) => lookupMyBookings(event)}>
          <label>
            Email address
            <input
              type="email"
              placeholder="you@example.com"
              value={lookupEmail}
              onChange={(event) => setLookupEmail(event.target.value)}
              required
            />
          </label>
          <button type="submit" className="outline-button" disabled={lookupLoading}>
            {lookupLoading && <span className="button-spinner" aria-hidden="true" />}
            {lookupLoading ? 'Searching…' : 'Find my bookings'}
          </button>
        </form>

        {lookupError && <p className="status-message error" role="alert" aria-live="assertive"><span className="alert-icon" aria-hidden="true">!</span>{lookupError}</p>}
        {lookupSearched && lookupBookings.length === 0 && !lookupLoading && (
          <p className="empty-state">No bookings found for that email.</p>
        )}
        {lookupBookings.length > 0 && (
          <div className="booking-results">
            {lookupBookings.map((booking) => (
              <article className="booking-result" key={booking.id}>
                <div>
                  <strong>{booking.name}</strong>
                  <span>{formatLocalDateTime(booking.created_at)}</span>
                </div>
                <span className={`booking-status ${booking.status}`}>{booking.status}</span>
              </article>
            ))}
          </div>
        )}
        {lookupCursor && (
          <button
            type="button"
            className="secondary-button next-page-button"
            onClick={() => lookupMyBookings(null, lookupCursor, false)}
            disabled={lookupLoading}
          >
            {lookupLoading && <span className="button-spinner" aria-hidden="true" />}
            {lookupLoading ? 'Loading…' : 'Next page'}
          </button>
        )}
      </section>

      <footer className="site-footer">
        <a className="footer-brand" href="#top"><span className="footer-mark" aria-hidden="true">✚</span>Slotwell</a>
        <span>Book your care, on your time.</span>
        <span>Made for your wellbeing <span aria-hidden="true">♥</span></span>
      </footer>
    </main>
  )
}
