export default function SimpleChart({ values = [] }) {
  const chartValues = values.length > 1 ? values : [0, ...(values.length ? values : [0])]
  const width = 760
  const height = 210
  const min = Math.min(...chartValues)
  const rawMax = Math.max(...chartValues)
  const max = rawMax === min ? min + 1 : rawMax
  const points = chartValues.map((value, index) => `${(index / (chartValues.length - 1)) * width},${height - ((value - min) / (max - min)) * height}`).join(' ')
  const area = `0,${height} ${points} ${width},${height}`
  return <div className="admin-chart-wrap">
    <div className="admin-chart-axis"><span>{rawMax.toLocaleString()}</span><span>{Math.round(rawMax * .75).toLocaleString()}</span><span>{Math.round(rawMax * .5).toLocaleString()}</span><span>{Math.round(rawMax * .25).toLocaleString()}</span><span>0</span></div>
    <svg className="admin-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="AI usage trend">
      <defs><linearGradient id="adminChartFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#596ff0" stopOpacity=".24"/><stop offset="100%" stopColor="#596ff0" stopOpacity="0"/></linearGradient></defs>
      {[0, 1, 2, 3, 4].map(n => <line key={n} x1="0" x2={width} y1={n * height / 4} y2={n * height / 4} stroke="#edf0f5" strokeDasharray="4 5" />)}
      <polygon points={area} fill="url(#adminChartFill)" />
      <polyline points={points} fill="none" stroke="#596ff0" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  </div>
}
