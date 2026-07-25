import {useId} from 'react';
import type {SceneChart} from '../scene-plan';
import {
  BODY_FONT,
  MONO_FONT,
  type Theme,
  easeOutCubic,
  formatNumber,
  niceMax,
} from './theme';

export type ChartProps = {
  chart: SceneChart;
  theme: Theme;
  progress: number;
  width: number;
  height: number;
};

const clean = (id: string) => id.replace(/[^a-zA-Z0-9]/g, '');

export const ChartFigure = (props: ChartProps) => {
  switch (props.chart.type) {
    case 'stat':
      return <StatCallout {...props} />;
    case 'line':
      return <LineChart {...props} />;
    case 'donut':
      return <DonutChart {...props} />;
    case 'comparison':
      return <ComparisonChart {...props} />;
    case 'bar':
    default:
      return <BarChart {...props} />;
  }
};

const AxisGrid = ({
  width,
  top,
  height,
  max,
  theme,
}: {
  width: number;
  top: number;
  height: number;
  max: number;
  theme: Theme;
}) => (
  <>
    {Array.from({length: 5}).map((_, index) => {
      const y = top + height * (index / 4);
      return (
        <g key={index}>
          <line x1={70} y1={y} x2={width} y2={y} stroke={theme.line} strokeWidth={2} />
          <text
            x={0}
            y={y + 8}
            fill={theme.muted}
            fontSize={22}
            fontFamily={MONO_FONT}
          >
            {formatNumber(max * (1 - index / 4))}
          </text>
        </g>
      );
    })}
  </>
);

export const BarChart = ({chart, theme, progress, width, height}: ChartProps) => {
  const data = chart.data.slice(0, 7);
  if (!data.length) return null;
  const eased = easeOutCubic(progress);
  const axisMax = niceMax(Math.max(...data.map((datum) => Math.abs(datum.value)), 1));
  const top = 82;
  const bottom = 82;
  const chartHeight = height - top - bottom;
  const availableWidth = width - 130;
  const gap = Math.max(22, Math.min(48, availableWidth / data.length / 3));
  const barWidth = Math.min(150, (availableWidth - gap * (data.length - 1)) / data.length);
  const startX = 100 + (availableWidth - (barWidth * data.length + gap * (data.length - 1))) / 2;
  const baseline = top + chartHeight;

  return (
    <svg width={width} height={height}>
      <AxisGrid width={width} top={top} height={chartHeight} max={axisMax} theme={theme} />
      {data.map((datum, index) => {
        const revealedHeight = (Math.abs(datum.value) / axisMax) * chartHeight * eased;
        const x = startX + index * (barWidth + gap);
        const y = baseline - revealedHeight;
        const color = theme.chartColors[index % theme.chartColors.length];
        return (
          <g key={`${datum.label}-${index}`}>
            <rect
              x={x}
              y={y}
              width={barWidth}
              height={revealedHeight}
              rx={8}
              fill={color}
            />
            <text
              x={x + barWidth / 2}
              y={y - 20}
              fill={theme.ink}
              fontSize={38}
              fontWeight={600}
              textAnchor="middle"
              fontFamily={MONO_FONT}
              opacity={eased}
            >
              {formatNumber(datum.value * eased)}
              {chart.unit}
            </text>
            <text
              x={x + barWidth / 2}
              y={baseline + 48}
              fill={theme.muted}
              fontSize={25}
              fontWeight={600}
              textAnchor="middle"
              fontFamily={BODY_FONT}
            >
              {datum.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
};

export const LineChart = ({chart, theme, progress, width, height}: ChartProps) => {
  const clipId = clean(useId());
  const data = chart.data.slice(0, 12);
  if (!data.length) return null;
  const eased = easeOutCubic(progress);
  const values = data.map((datum) => datum.value);
  const max = niceMax(Math.max(...values, 1));
  const min = Math.min(...values, 0);
  const left = 90;
  const right = 38;
  const top = 64;
  const bottom = 82;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const points = data.map((datum, index) => ({
    datum,
    x: left + (data.length === 1 ? chartWidth / 2 : chartWidth * (index / (data.length - 1))),
    y: top + chartHeight - ((datum.value - min) / (max - min || 1)) * chartHeight,
  }));
  const path = points.map((point, index) => `${index ? 'L' : 'M'}${point.x},${point.y}`).join(' ');

  return (
    <svg width={width} height={height}>
      <AxisGrid width={width} top={top} height={chartHeight} max={max} theme={theme} />
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={0} width={left + chartWidth * eased} height={height} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        <path
          d={path}
          fill="none"
          stroke={theme.primary}
          strokeWidth={10}
          strokeLinecap="square"
          strokeLinejoin="round"
        />
        {points.map((point, index) => (
          <rect
            key={index}
            x={point.x - 10}
            y={point.y - 10}
            width={20}
            height={20}
            fill={theme.chartColors[index % theme.chartColors.length]}
          />
        ))}
      </g>
      {points.map((point, index) => (
        <text
          key={index}
          x={point.x}
          y={top + chartHeight + 48}
          fill={theme.muted}
          fontSize={24}
          textAnchor="middle"
          fontFamily={BODY_FONT}
        >
          {point.datum.label}
        </text>
      ))}
    </svg>
  );
};

export const DonutChart = ({chart, theme, progress, width, height}: ChartProps) => {
  const data = chart.data.slice(0, 6);
  if (!data.length) return null;
  const eased = easeOutCubic(progress);
  const total = data.reduce((sum, datum) => sum + Math.abs(datum.value), 0) || 1;
  const cx = width * 0.38;
  const cy = height / 2;
  const radius = Math.min(height * 0.34, 190);
  const strokeWidth = 56;
  const circumference = 2 * Math.PI * radius;
  let cumulative = 0;

  return (
    <svg width={width} height={height}>
      <circle
        cx={cx}
        cy={cy}
        r={radius}
        fill="none"
        stroke={theme.chartTrack}
        strokeWidth={strokeWidth}
      />
      {data.map((datum, index) => {
        const fraction = Math.abs(datum.value) / total;
        const start = cumulative;
        cumulative += fraction;
        const visible = Math.max(0, Math.min(fraction, eased - start));
        return (
          <circle
            key={index}
            cx={cx}
            cy={cy}
            r={radius}
            fill="none"
            stroke={theme.chartColors[index % theme.chartColors.length]}
            strokeWidth={strokeWidth}
            strokeDasharray={`${circumference * visible} ${circumference}`}
            strokeDashoffset={-circumference * start}
            transform={`rotate(-90 ${cx} ${cy})`}
          />
        );
      })}
      <text
        x={cx}
        y={cy + 10}
        fill={theme.ink}
        fontSize={76}
        fontWeight={700}
        textAnchor="middle"
        fontFamily={MONO_FONT}
      >
        {formatNumber(total * eased)}
        {chart.unit}
      </text>
      <g transform={`translate(${width * 0.68} ${height * 0.19})`}>
        {data.map((datum, index) => (
          <g key={index} transform={`translate(0 ${index * 74})`}>
            <rect
              width={24}
              height={24}
              y={-18}
              fill={theme.chartColors[index % theme.chartColors.length]}
            />
            <text x={42} fill={theme.ink} fontSize={30} fontFamily={BODY_FONT}>
              {datum.label}
            </text>
            <text x={310} fill={theme.muted} fontSize={28} textAnchor="end" fontFamily={MONO_FONT}>
              {Math.round((Math.abs(datum.value) / total) * 100)}%
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
};

export const StatCallout = ({chart, theme, progress, width, height}: ChartProps) => {
  const datum = chart.data[0] ?? {label: '', value: 0};
  const eased = easeOutCubic(progress);
  return (
    <svg width={width} height={height}>
      <rect
        x={40}
        y={60}
        width={Math.max(12, (width - 80) * eased)}
        height={18}
        fill={theme.accent}
      />
      <text
        x={width / 2}
        y={height * 0.52}
        fill={theme.ink}
        fontSize={Math.min(height * 0.57, 340)}
        fontWeight={700}
        textAnchor="middle"
        dominantBaseline="middle"
        fontFamily={MONO_FONT}
      >
        {formatNumber(datum.value * eased)}
        <tspan fill={theme.accent} fontSize={Math.min(height * 0.2, 120)}>
          {chart.unit}
        </tspan>
      </text>
      <text
        x={width / 2}
        y={height * 0.88}
        fill={theme.muted}
        fontSize={38}
        fontWeight={500}
        textAnchor="middle"
        fontFamily={BODY_FONT}
      >
        {chart.caption || datum.label}
      </text>
    </svg>
  );
};

export const ComparisonChart = ({chart, theme, progress, width, height}: ChartProps) => {
  const data = chart.data.slice(0, 4);
  if (!data.length) return null;
  const eased = easeOutCubic(progress);
  const max = niceMax(Math.max(...data.map((datum) => Math.abs(datum.value)), 1));
  const labelWidth = 300;
  const valueWidth = 170;
  const trackWidth = width - labelWidth - valueWidth;
  const rowHeight = Math.min(92, (height - 70) / data.length - 24);

  return (
    <svg width={width} height={height}>
      {data.map((datum, index) => {
        const y = 44 + index * (rowHeight + 28);
        const barWidth = Math.max(4, (Math.abs(datum.value) / max) * trackWidth * eased);
        return (
          <g key={index}>
            <text
              x={0}
              y={y + rowHeight / 2}
              fill={theme.ink}
              fontSize={32}
              fontWeight={600}
              dominantBaseline="middle"
              fontFamily={BODY_FONT}
            >
              {datum.label}
            </text>
            <rect
              x={labelWidth}
              y={y}
              width={trackWidth}
              height={rowHeight}
              fill={theme.chartTrack}
            />
            <rect
              x={labelWidth}
              y={y}
              width={barWidth}
              height={rowHeight}
              fill={theme.chartColors[index % theme.chartColors.length]}
            />
            <text
              x={width}
              y={y + rowHeight / 2}
              fill={theme.ink}
              fontSize={34}
              fontWeight={600}
              textAnchor="end"
              dominantBaseline="middle"
              fontFamily={MONO_FONT}
            >
              {formatNumber(datum.value * eased)}
              {chart.unit}
            </text>
          </g>
        );
      })}
    </svg>
  );
};
