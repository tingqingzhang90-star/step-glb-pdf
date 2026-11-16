// 工程图表格预设:插入"表格"按钮默认放置的模板
// 数据契约与后端 dim_pdf_sheet._draw_table_placement 一致:
//   col_widths/row_heights 单位 mm(SVG 坐标即 mm)
//   cells 一维数组,只列合并格的左上角,被覆盖格不出现
//   align 形如 "h-left v-center"(水平 left/center/right)

export const TECH_PARAMS_TABLE = {
  col_widths: [40, 40, 40, 40],
  row_heights: [14, 8, 8, 8, 8, 8, 8, 8],
  border: { width: 0.3, color: '#303133' },
  text_color: '#303133',
  cells: [
    { r: 0, c: 0, colspan: 4, text: '技术参数', align: 'h-center v-center', font_size: 16 },
    { r: 1, c: 0, text: '产品型号', align: 'h-left' },
    { r: 1, c: 1, colspan: 3, text: '', align: 'h-left' },
    { r: 2, c: 0, text: '缸径', align: 'h-left' },
    { r: 2, c: 1, text: '', align: 'h-center' },
    { r: 2, c: 2, text: '有效行程', align: 'h-center' },
    { r: 2, c: 3, text: '', align: 'h-center' },
    { r: 3, c: 0, text: '电机功率', align: 'h-left' },
    { r: 3, c: 1, text: '', align: 'h-center' },
    { r: 3, c: 2, text: '额定转速', align: 'h-center' },
    { r: 3, c: 3, text: '', align: 'h-center' },
    { r: 4, c: 0, text: '额定扭矩', align: 'h-left' },
    { r: 4, c: 1, text: '', align: 'h-center' },
    { r: 4, c: 2, text: '最高转速', align: 'h-center' },
    { r: 4, c: 3, text: '', align: 'h-center' },
    { r: 5, c: 0, text: '丝杆导程', align: 'h-left' },
    { r: 5, c: 1, text: '', align: 'h-center' },
    { r: 5, c: 2, text: '减速比', align: 'h-center' },
    { r: 5, c: 3, text: '', align: 'h-center' },
    { r: 6, c: 0, text: '额定推力', align: 'h-left' },
    { r: 6, c: 1, text: '', align: 'h-center' },
    { r: 6, c: 2, text: '额定速度', align: 'h-center' },
    { r: 6, c: 3, text: '', align: 'h-center' },
    { r: 7, c: 0, text: '电缸安装方式', align: 'h-left' },
    { r: 7, c: 1, colspan: 3, text: '', align: 'h-left' }
  ]
}
