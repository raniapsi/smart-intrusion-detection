import type { Classification } from '../api/types'

// Format a UTC ISO timestamp as a short HH:MM:SS string in the user's
// local timezone. Used in event rows where space is tight.
export function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return iso
  }
}

export function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('en-GB', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return iso
  }
}

// Tailwind classes for each classification. Centralised so the dashboard
// stays visually consistent across components.
export function classificationColors(c: Classification): {
  bg: string
  text: string
  border: string
  ring: string
} {
  switch (c) {
    case 'CRITICAL':
      return {
        bg: 'bg-critical-soft',
        text: 'text-critical',
        border: 'border-critical',
        ring: 'ring-critical',
      }
    case 'SUSPECT':
      return {
        bg: 'bg-suspect-soft',
        text: 'text-suspect',
        border: 'border-suspect',
        ring: 'ring-suspect',
      }
    case 'NORMAL':
    default:
      return {
        bg: 'bg-normal-soft',
        text: 'text-normal',
        border: 'border-normal',
        ring: 'ring-normal',
      }
  }
}

// Sensitivity ordering: how "important" a zone looks on the map.
export function sensitivityWeight(
  s: 'PUBLIC' | 'STANDARD' | 'RESTRICTED' | 'CRITICAL',
): number {
  return { PUBLIC: 0, STANDARD: 1, RESTRICTED: 2, CRITICAL: 3 }[s]
}

export function clampScore(score: number): number {
  return Math.max(0, Math.min(1, score))
}