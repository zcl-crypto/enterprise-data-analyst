from enterprise.analysis import analyze, markdown_report


def test_weighted_rate_is_not_average_of_percentages():
    result = analyze('department_name,month,order_count,refunded_orders,refund_rate\nA,2026-07,10,5,50\nA,2026-08,90,9,10\n')
    assert result['kpis'][2]['value'] == '14.00%'
    assert result['charts'][0]['option']['series'][0]['data'] == [14.0]


def test_truncated_results_never_report_population_anomalies():
    data = 'department_name,order_count,refunded_orders\nA,100,40\nB,100,5\nC,100,5\nD,100,5\n'
    assert analyze(data)['anomalies'][0]['dimension'] == 'A'
    result = analyze(data, truncated=True)
    assert not result['anomalies']
    assert '不能作为完整总体结论' in result['insights'][0]


def test_duplicate_chart_coordinates_do_not_drop_rows():
    result = analyze('month,sales_amount\n2026-07,10\n2026-07,20\n')
    assert result['row_count'] == 2
    assert result['charts'] == []


def test_empty_result_is_explained_without_fabricated_statistics():
    result = analyze('month,sales_amount\n', sql='SELECT ...', question='测试')
    assert result['charts'] == [] and result['kpis'] == []
    assert '没有返回数据' in result['insights'][0]
    assert 'SELECT ...' in markdown_report(result)


def test_missing_time_points_remain_null_in_multiseries():
    result = analyze('month,department_name,sales_amount\n2026-07,A,10\n2026-08,B,20\n')
    assert result['charts'][0]['option']['series'][0]['data'] == [10, None]
