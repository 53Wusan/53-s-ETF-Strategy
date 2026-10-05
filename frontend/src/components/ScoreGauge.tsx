type Props = { score: number; compact?: boolean }

export default function ScoreGauge({ score, compact = false }: Props) {
  const normalized = Math.max(0, Math.min(100, (score + 100) / 2))
  const tone = score <= -60 ? 'fear' : score >= 60 ? 'greed' : 'neutral'
  return (
    <div className={`score-gauge ${compact ? 'compact' : ''}`} aria-label={`贪恐值 ${score.toFixed(1)}`}>
      <div className="score-track">
        <span className="score-marker" style={{ left: `${normalized}%` }} />
      </div>
      <div className="score-labels"><span>-100 恐惧</span><span>0</span><span>贪婪 100</span></div>
      <strong className={tone}>{score.toFixed(1)}</strong>
    </div>
  )
}

