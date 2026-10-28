import { useCallback, useEffect, useMemo, useState } from 'react'

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

    setBookingLoading(true)
    setMessage({ type: '', text: '' })

    try {
      const booking = await requestJson('/bookings', {
        method: 'POST',
        body: JSON.stringify({
          slot_id: selectedSlot.id,
          name: formData.name,
          email: formData.email,
        }),
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
      setMessage({ type: 'error', text: error.message || 'Booking failed.' })
    } finally {
      setBookingLoading(false)
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
      <div className="page-header">
        <div>
          <p className="eyebrow">Clinic booking</p>
          <h1>Book your consultation</h1>
        </div>
        {!apiKey && (
          <div className="env-warning">
            Set VITE_API_KEY in frontend/.env before using the app.
          </div>
        )}
      </div>

      <section className="panel">
        <div className="panel-heading">
          <h2>Available slots</h2>
          <label className="provider-filter">
            <span>Provider</span>
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
          <p className="status-message info">Loading slots… the API may be waking up.</p>
        ) : slotsError ? (
          <p className="status-message error">{slotsError}</p>
        ) : (
          <div className="slots-grid">
            {slots.length === 0 ? (
              <p className="empty-state">No slots are available for this provider.</p>
            ) : (
              slots.map((slot) => (
                <article
                  key={slot.id}
                  className={`slot-card ${slot.available ? 'available' : 'unavailable'} ${
                    selectedSlotId === slot.id ? 'selected' : ''
                  }`}
                >
                  <div>
                    <p className="slot-provider">{slot.provider}</p>
                    <p className="slot-times">
                      {formatLocalDateTime(slot.start)} – {formatLocalDateTime(slot.end)}
                    </p>
                  </div>

                  <div className="slot-actions">
                    <span className={`availability ${slot.available ? 'open' : 'closed'}`}>
                      {slot.available ? 'Available' : 'Unavailable'}
                    </span>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => setSelectedSlotId(slot.id)}
                      disabled={!slot.available}
                    >
                      {selectedSlotId === slot.id ? 'Selected' : 'Select'}
                    </button>
                  </div>
                </article>
              ))
            )}
          </div>
        )}
      </section>

      <section className="panel booking-panel">
        <h2>Book a slot</h2>

        <form onSubmit={handleBookingSubmit} className="booking-form">
          <label>
            Selected slot
            <input
              type="text"
              value={selectedSlot ? `${selectedSlot.provider} · ${formatLocalDateTime(selectedSlot.start)}` : 'Choose an available slot'}
              readOnly
            />
          </label>

          <label>
            Full name
            <input
              type="text"
              placeholder="Jane Doe"
              value={formData.name}
              onChange={(event) => setFormData((current) => ({ ...current, name: event.target.value }))}
              required
            />
          </label>

          <label>
            Email address
            <input
              type="email"
              placeholder="jane@example.com"
              value={formData.email}
              onChange={(event) => setFormData((current) => ({ ...current, email: event.target.value }))}
              required
            />
          </label>

          <button type="submit" disabled={bookingLoading || !selectedSlot || !selectedSlot.available}>
            {bookingLoading ? 'Booking…' : 'Book appointment'}
          </button>
        </form>
      </section>

      {message.text && (
        <div className={`status-message ${message.type === 'success' ? 'success' : 'error'}`}>
          {message.text}
        </div>
      )}

      {confirmation && (
        <section className="panel confirmation-panel">
          <h2>Booking confirmation</h2>
          <p>
            <strong>{confirmation.name}</strong> · {confirmation.email}
          </p>
          <p>
            {confirmation.slot?.provider || 'Clinic'} · {formatLocalDateTime(confirmation.slot?.start || confirmation.created_at)}
          </p>
          <p>Status: {confirmation.status}</p>
          <p>Booking ID: {confirmation.id}</p>

          <button type="button" className="danger-button" onClick={handleCancelBooking} disabled={cancelLoading}>
            {cancelLoading ? 'Cancelling…' : 'Cancel booking'}
          </button>
        </section>
      )}
    </main>
  )
}
