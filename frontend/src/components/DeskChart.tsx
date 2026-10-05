import ReactEChartsCore from 'echarts-for-react/esm/core'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkAreaComponent, MarkLineComponent, CanvasRenderer])
export default function DeskChart({ option, height = 330 }: { option: echarts.EChartsCoreOption; height?: number }) {
  return <ReactEChartsCore echarts={echarts} option={option} style={{ height }} notMerge />
}
