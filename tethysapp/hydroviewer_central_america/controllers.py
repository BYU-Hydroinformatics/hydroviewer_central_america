import datetime as dt
import json
import os
from csv import writer as csv_writer

import netCDF4 as nc
import numpy as np
import plotly.graph_objs as go
import requests
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from requests.auth import HTTPBasicAuth
from tethys_sdk.gizmos import *
from tethys_sdk.permissions import has_permission
import geoglows

from .app import Hydroviewer as app
from .helpers import *

base_name = __package__.split('.')[-1]


def set_custom_setting(defaultModelName, defaultWSName):
    from tethys_apps.models import TethysApp
    db_app = TethysApp.objects.get(package=app.package)

    db_setting = db_app.custom_settings.get(name='default_model_type')
    db_setting.value = defaultModelName
    db_setting.save()

    db_setting = db_app.custom_settings.get(name='default_watershed_name')
    db_setting.value = defaultWSName
    db_setting.save()
    return


def home(request):
    # Check if we have a default model. If we do, then redirect the user to the default model's page
    default_model = app.get_custom_setting('default_model_type')
    if default_model:
        model_func = switch_model(default_model)
        if model_func is not 'invalid':
            return globals()[model_func](request)
        else:
            return home_standard(request)
    else:
        return home_standard(request)


def home_standard(request):
    model_input = SelectInput(display_text='',
                              name='model',
                              multiple=False,
                              options=[('Select Model', ''), ('ECMWF-RAPID', 'ecmwf'), ('LIS-RAPID', 'lis'),
                                       ('HIWAT-RAPID', 'hiwat')],
                              initial=['Select Model'],
                              original=True)

    zoom_info = TextInput(display_text='',
                          initial=json.dumps(app.get_custom_setting('zoom_info')),
                          name='zoom_info',
                          disabled=True)

    region_index = json.load(open(os.path.join(os.path.dirname(__file__), 'public', 'geojson', 'index.json')))
    regions = SelectInput(
        display_text='Zoom to a Region:',
        name='regions',
        multiple=False,
        original=True,
        options=[(region_index[opt]['name'], opt) for opt in region_index]
    )

    # Retrieve a geoserver engine and geoserver credentials.
    geoserver_engine = app.get_spatial_dataset_service(
        name='main_geoserver', as_engine=True)

    my_geoserver = geoserver_engine.endpoint.replace('rest', '')

    geoserver_base_url = my_geoserver
    geoserver_workspace = app.get_custom_setting('workspace')
    region = app.get_custom_setting('region')
    extra_feature = app.get_custom_setting('extra_feature')
    layer_name = app.get_custom_setting('layer_name')

    geoserver_endpoint = TextInput(display_text='',
                                   initial=json.dumps(
                                       [geoserver_base_url, geoserver_workspace, region, extra_feature, layer_name]),
                                   name='geoserver_endpoint',
                                   disabled=True)

    context = {
        "base_name": base_name,
        "model_input": model_input,
        "zoom_info": zoom_info,
        "regions": regions,
        "geoserver_endpoint": geoserver_endpoint
    }

    return render(request, '{0}/home.html'.format(base_name), context)


def ecmwf(request):
    # Can Set Default permissions : Only allowed for admin users
    can_update_default = has_permission(request, 'update_default')

    if (can_update_default):
        defaultUpdateButton = Button(
            display_text='Save',
            name='update_button',
            style='success',
            attributes={
                'data-toggle': 'tooltip',
                'data-placement': 'bottom',
                'title': 'Save as Default Options for WS'
            })
    else:
        defaultUpdateButton = False

    # Check if we need to hide the WS options dropdown.
    hiddenAttr = ""
    if app.get_custom_setting('show_dropdown') and app.get_custom_setting(
            'default_model_type') and app.get_custom_setting('default_watershed_name'):
        hiddenAttr = "hidden"

    default_model = app.get_custom_setting('default_model_type')
    init_model_val = request.GET.get('model', False) or default_model or 'Select Model'
    init_ws_val = app.get_custom_setting('default_watershed_name') or 'Select Watershed'

    model_input = SelectInput(display_text='',
                              name='model',
                              multiple=False,
                              options=[('Select Model', ''), ('ECMWF-RAPID', 'ecmwf'), ('LIS-RAPID', 'lis'),
                                       ('HIWAT-RAPID', 'hiwat')],
                              initial=[init_model_val],
                              classes=hiddenAttr,
                              original=True)

    # uncomment for displaying watersheds in the SPT
    # res = requests.get(app.get_custom_setting('api_source') + '/apps/streamflow-prediction-tool/api/GetWatersheds/',
    #                    headers={'Authorization': 'Token ' + app.get_custom_setting('spt_token')})
    #
    # watershed_list_raw = json.loads(res.content)
    #
    # app.get_custom_setting('keywords').lower().replace(' ', '').split(',')
    # watershed_list = [value for value in watershed_list_raw if
    #                   any(val in value[0].lower().replace(' ', '') for
    #                       val in app.get_custom_setting('keywords').lower().replace(' ', '').split(','))]

    # Retrieve a geoserver engine and geoserver credentials.
    geoserver_engine = app.get_spatial_dataset_service(
        name='main_geoserver', as_engine=True)

    geos_username = geoserver_engine.username
    geos_password = geoserver_engine.password
    my_geoserver = geoserver_engine.endpoint.replace('rest', '')

    watershed_list = [['Select Watershed', '']]  # + watershed_list
    res2 = requests.get(my_geoserver + 'rest/workspaces/' + app.get_custom_setting('workspace') + '/featuretypes.json',
                        auth=HTTPBasicAuth(geos_username, geos_password), verify=False)

    for i in range(len(json.loads(res2.content)['featureTypes']['featureType'])):
        raw_feature = json.loads(res2.content)['featureTypes']['featureType'][i]['name']
        if 'drainage_line' in raw_feature and any(
                n in raw_feature for n in app.get_custom_setting('keywords').replace(' ', '').split(',')):
            feat_name = raw_feature.split('-')[0].replace('_', ' ').title() + ' (' + \
                        raw_feature.split('-')[1].replace('_', ' ').title() + ')'
            if feat_name not in str(watershed_list):
                watershed_list.append([feat_name, feat_name])

    # Add the default WS if present and not already in the list
    if default_model == 'ECMWF-RAPID' and init_ws_val and init_ws_val not in str(watershed_list):
        watershed_list.append([init_ws_val, init_ws_val])

    watershed_select = SelectInput(display_text='',
                                   name='watershed',
                                   options=watershed_list,
                                   initial=[init_ws_val],
                                   original=True,
                                   classes=hiddenAttr,
                                   attributes={'onchange': "javascript:view_watershed();" + hiddenAttr}
                                   )

    zoom_info = TextInput(display_text='',
                          initial=json.dumps(app.get_custom_setting('zoom_info')),
                          name='zoom_info',
                          disabled=True)

    # Retrieve a geoserver engine and geoserver credentials.
    geoserver_engine = app.get_spatial_dataset_service(
        name='main_geoserver', as_engine=True)

    my_geoserver = geoserver_engine.endpoint.replace('rest', '')

    geoserver_base_url = my_geoserver
    geoserver_workspace = app.get_custom_setting('workspace')
    region = ''
    extra_feature = app.get_custom_setting('extra_feature')
    layer_name = app.get_custom_setting('layer_name')

    geoserver_endpoint = TextInput(display_text='',
                                   initial=json.dumps(
                                       [geoserver_base_url, geoserver_workspace, region, extra_feature, layer_name]),
                                   name='geoserver_endpoint',
                                   disabled=True)

    region_index = json.load(open(os.path.join(os.path.dirname(__file__), 'public', 'geojson', 'index.json')))
    regions = SelectInput(
        display_text='Zoom to a Region:',
        name='regions',
        multiple=False,
        original=True,
        options=[(region_index[opt]['name'], opt) for opt in region_index]
    )

    context = {
        "base_name": base_name,
        "model_input": model_input,
        "watershed_select": watershed_select,
        "zoom_info": zoom_info,
        "geoserver_endpoint": geoserver_endpoint,
        "defaultUpdateButton": defaultUpdateButton,
        "regions": regions
    }

    return render(request, '{0}/ecmwf.html'.format(base_name), context)


def lis(request):
    # Can Set Default permissions : Only allowed for admin users
    can_update_default = has_permission(request, 'update_default')

    if (can_update_default):
        defaultUpdateButton = Button(
            display_text='Save',
            name='update_button',
            style='success',
            attributes={
                'data-toggle': 'tooltip',
                'data-placement': 'bottom',
                'title': 'Save as Default Options for WS'
            })
    else:
        defaultUpdateButton = False

    # Check if we need to hide the WS options dropdown.
    hiddenAttr = ""
    if app.get_custom_setting('show_dropdown') and app.get_custom_setting(
            'default_model_type') and app.get_custom_setting('default_watershed_name'):
        hiddenAttr = "hidden"

    default_model = app.get_custom_setting('default_model_type')
    init_model_val = request.GET.get('model', False) or default_model or 'Select Model'
    init_ws_val = app.get_custom_setting('default_watershed_name') or 'Select Watershed'

    model_input = SelectInput(display_text='',
                              name='model',
                              multiple=False,
                              options=[('Select Model', ''), ('ECMWF-RAPID', 'ecmwf'), ('LIS-RAPID', 'lis'),
                                       ('HIWAT-RAPID', 'hiwat')],
                              initial=[init_model_val],
                              classes=hiddenAttr,
                              original=True)

    watershed_list = [['Select Watershed', '']]

    if app.get_custom_setting('lis_path'):
        res = os.listdir(app.get_custom_setting('lis_path'))

        for i in res:
            feat_name = i.split('-')[0].replace('_', ' ').title() + ' (' + \
                        i.split('-')[1].replace('_', ' ').title() + ')'
            if feat_name not in str(watershed_list):
                watershed_list.append([feat_name, i])

    # Add the default WS if present and not already in the list
    if default_model == 'LIS-RAPID' and init_ws_val and init_ws_val not in str(watershed_list):
        watershed_list.append([init_ws_val, init_ws_val])

    watershed_select = SelectInput(display_text='',
                                   name='watershed',
                                   options=watershed_list,
                                   initial=[init_ws_val],
                                   original=True,
                                   classes=hiddenAttr,
                                   attributes={'onchange': "javascript:view_watershed();"}
                                   )

    zoom_info = TextInput(display_text='',
                          initial=json.dumps(app.get_custom_setting('zoom_info')),
                          name='zoom_info',
                          disabled=True)

    # Retrieve a geoserver engine and geoserver credentials.
    geoserver_engine = app.get_spatial_dataset_service(
        name='main_geoserver', as_engine=True)

    my_geoserver = geoserver_engine.endpoint.replace('rest', '')

    geoserver_base_url = my_geoserver
    geoserver_workspace = app.get_custom_setting('workspace')
    region = app.get_custom_setting('region')
    extra_feature = app.get_custom_setting('extra_feature')
    layer_name = app.get_custom_setting('layer_name')

    geoserver_endpoint = TextInput(display_text='',
                                   initial=json.dumps(
                                       [geoserver_base_url, geoserver_workspace, region, extra_feature, layer_name]),
                                   name='geoserver_endpoint',
                                   disabled=True)

    context = {
        "base_name": base_name,
        "model_input": model_input,
        "watershed_select": watershed_select,
        "zoom_info": zoom_info,
        "geoserver_endpoint": geoserver_endpoint,
        "defaultUpdateButton": defaultUpdateButton
    }

    return render(request, '{0}/lis.html'.format(base_name), context)


def hiwat(request):
    # Can Set Default permissions : Only allowed for admin users
    can_update_default = has_permission(request, 'update_default')

    if (can_update_default):
        defaultUpdateButton = Button(
            display_text='Save',
            name='update_button',
            style='success',
            attributes={
                'data-toggle': 'tooltip',
                'data-placement': 'bottom',
                'title': 'Save as Default Options for WS'
            })
    else:
        defaultUpdateButton = False

    # Check if we need to hide the WS options dropdown.
    hiddenAttr = ""
    if app.get_custom_setting('show_dropdown') and app.get_custom_setting(
            'default_model_type') and app.get_custom_setting('default_watershed_name'):
        hiddenAttr = "hidden"

    default_model = app.get_custom_setting('default_model_type')
    init_model_val = request.GET.get('model', False) or default_model or 'Select Model'
    init_ws_val = app.get_custom_setting('default_watershed_name') or 'Select Watershed'

    model_input = SelectInput(display_text='',
                              name='model',
                              multiple=False,
                              options=[('Select Model', ''), ('ECMWF-RAPID', 'ecmwf'), ('LIS-RAPID', 'lis'),
                                       ('HIWAT-RAPID', 'hiwat')],
                              initial=[init_model_val],
                              classes=hiddenAttr,
                              original=True)

    watershed_list = [['Select Watershed', '']]

    if app.get_custom_setting('hiwat_path'):
        res = os.listdir(app.get_custom_setting('hiwat_path'))

        for i in res:
            feat_name = i.split('-')[0].replace('_', ' ').title() + ' (' + \
                        i.split('-')[1].replace('_', ' ').title() + ')'
            if feat_name not in str(watershed_list):
                watershed_list.append([feat_name, i])

    # Add the default WS if present and not already in the list
    if default_model == 'HIWAT-RAPID' and init_ws_val and init_ws_val not in str(watershed_list):
        watershed_list.append([init_ws_val, init_ws_val])

    watershed_select = SelectInput(display_text='',
                                   name='watershed',
                                   options=watershed_list,
                                   initial=[init_ws_val],
                                   classes=hiddenAttr,
                                   original=True,
                                   attributes={'onchange': "javascript:view_watershed();"}
                                   )

    zoom_info = TextInput(display_text='',
                          initial=json.dumps(app.get_custom_setting('zoom_info')),
                          name='zoom_info',
                          disabled=True)

    # Retrieve a geoserver engine and geoserver credentials.
    geoserver_engine = app.get_spatial_dataset_service(
        name='main_geoserver', as_engine=True)

    my_geoserver = geoserver_engine.endpoint.replace('rest', '')

    geoserver_base_url = my_geoserver
    geoserver_workspace = app.get_custom_setting('workspace')
    region = app.get_custom_setting('region')
    extra_feature = app.get_custom_setting('extra_feature')
    layer_name = app.get_custom_setting('layer_name')

    geoserver_endpoint = TextInput(display_text='',
                                   initial=json.dumps(
                                       [geoserver_base_url, geoserver_workspace, region, extra_feature, layer_name]),
                                   name='geoserver_endpoint',
                                   disabled=True)

    context = {
        "base_name": base_name,
        "model_input": model_input,
        "watershed_select": watershed_select,
        "zoom_info": zoom_info,
        "geoserver_endpoint": geoserver_endpoint,
        "defaultUpdateButton": defaultUpdateButton
    }

    return render(request, '{0}/hiwat.html'.format(base_name), context)


def get_warning_points(request):
    get_data = request.GET
    if get_data['model'] == 'ECMWF-RAPID':
        try:
            watershed = get_data['watershed']
            subbasin = get_data['subbasin']

            res20 = requests.get(
                app.get_custom_setting(
                    'api_source') + '/apps/streamflow-prediction-tool/api/GetWarningPoints/?watershed_name=' +
                watershed + '&subbasin_name=' + subbasin + '&return_period=20',
                headers={'Authorization': 'Token ' + app.get_custom_setting('spt_token')}, verify=False)

            res10 = requests.get(
                app.get_custom_setting(
                    'api_source') + '/apps/streamflow-prediction-tool/api/GetWarningPoints/?watershed_name=' +
                watershed + '&subbasin_name=' + subbasin + '&return_period=10',
                headers={'Authorization': 'Token ' + app.get_custom_setting('spt_token')}, verify=False)

            res2 = requests.get(
                app.get_custom_setting(
                    'api_source') + '/apps/streamflow-prediction-tool/api/GetWarningPoints/?watershed_name=' +
                watershed + '&subbasin_name=' + subbasin + '&return_period=2',
                headers={'Authorization': 'Token ' + app.get_custom_setting('spt_token')}, verify=False)

            return JsonResponse({
                "success": "Data analysis complete!",
                "warning20": json.loads(res20.content)["features"],
                "warning10": json.loads(res10.content)["features"],
                "warning2": json.loads(res2.content)["features"]
            })
        except Exception as e:
            print(str(e))
            return JsonResponse({'error': 'No data found for the selected reach.'})
    else:
        pass


def ecmwf_get_time_series(request):
    get_data = request.GET
    try:
        comid = get_data['comid']

        stats = geoglows.streamflow.forecast_stats(comid)
        rperiods = geoglows.streamflow.return_periods(comid)
        title = {'Upstream Drainage Area': get_data['tot_drain_area']}
        return JsonResponse({'plot': geoglows.plots.forecast_stats(
            stats, rperiods, titles=title, outformat='plotly_html')})
    except Exception as e:
        print(str(e))
        return JsonResponse({'error': 'No data found for the selected reach.'})


def get_time_series(request):
    return ecmwf_get_time_series(request)


def lis_get_time_series(request):
    get_data = request.GET

    try:
        # model = get_data['model']
        watershed = get_data['watershed']
        subbasin = get_data['subbasin']
        comid = get_data['comid']
        units = 'metric'

        path = os.path.join(app.get_custom_setting('lis_path'), '-'.join([watershed, subbasin]))
        filename = [f for f in os.listdir(path) if 'Qout' in f]
        res = nc.Dataset(os.path.join(app.get_custom_setting('lis_path'), '-'.join([watershed, subbasin]), filename[0]),
                         'r')

        dates_raw = res.variables['time'][:]
        dates = []
        for d in dates_raw:
            dates.append(dt.datetime.fromtimestamp(d))

        comid_list = res.variables['rivid'][:]
        comid_index = int(np.where(comid_list == int(comid))[0])

        values = []
        for l in list(res.variables['Qout'][:]):
            values.append(float(l[comid_index]))

        # --------------------------------------
        # Chart Section
        # --------------------------------------
        series = go.Scatter(
            name='LDAS',
            x=dates,
            y=values,
        )

        layout = go.Layout(
            title="LDAS Streamflow<br><sub>{0} ({1}): {2}</sub>".format(
                watershed, subbasin, comid),
            xaxis=dict(
                title='Date',
            ),
            yaxis=dict(
                title='Streamflow ({}<sup>3</sup>/s)'
                    .format(get_units_title(units))
            )
        )

        chart_obj = PlotlyView(
            go.Figure(data=[series],
                      layout=layout)
        )

        context = {
            'gizmo_object': chart_obj,
        }

        return render(request, '{0}/gizmo_ajax.html'.format(base_name), context)

    except Exception as e:
        print(str(e))
        return JsonResponse({'error': 'No LIS data found for the selected reach.'})


def hiwat_get_time_series(request):
    get_data = request.GET

    try:
        # model = get_data['model']
        watershed = get_data['watershed']
        subbasin = get_data['subbasin']
        comid = get_data['comid']
        units = 'metric'

        path = os.path.join(app.get_custom_setting('hiwat_path'), '-'.join([watershed, subbasin]))
        filename = [f for f in os.listdir(path) if 'Qout' in f]
        res = nc.Dataset(
            os.path.join(app.get_custom_setting('hiwat_path'), '-'.join([watershed, subbasin]), filename[0]), 'r')

        dates_raw = res.variables['time'][:]
        dates = []
        for d in dates_raw:
            dates.append(dt.datetime.fromtimestamp(d))

        comid_list = res.variables['rivid'][:]
        comid_index = int(np.where(comid_list == int(comid))[0])

        values = []
        for l in list(res.variables['Qout'][:]):
            values.append(float(l[comid_index]))

        # --------------------------------------
        # Chart Section
        # --------------------------------------
        series = go.Scatter(
            name='HIWAT',
            x=dates,
            y=values,
        )

        layout = go.Layout(
            title="HIWAT Streamflow<br><sub>{0} ({1}): {2}</sub>".format(
                watershed, subbasin, comid),
            xaxis=dict(
                title='Date',
            ),
            yaxis=dict(
                title='Streamflow ({}<sup>3</sup>/s)'
                    .format(get_units_title(units))
            )
        )

        chart_obj = PlotlyView(
            go.Figure(data=[series],
                      layout=layout)
        )

        context = {
            'gizmo_object': chart_obj,
        }

        return render(request, '{0}/gizmo_ajax.html'.format(base_name), context)

    except Exception as e:
        print(str(e))
        return JsonResponse({'error': 'No HIWAT data found for the selected reach.'})


def get_available_dates(request):
    get_data = request.GET

    watershed = get_data['watershed']
    subbasin = get_data['subbasin']
    comid = get_data['comid']

    res = requests.get(
        app.get_custom_setting(
            'api_source') + '/apps/streamflow-prediction-tool/api/GetAvailableDates/?watershed_name=' +
        watershed + '&subbasin_name=' + subbasin, verify=False,
        headers={'Authorization': 'Token ' + app.get_custom_setting('spt_token')})

    dates = []
    for date in eval(res.content):
        if len(date) == 10:
            date_mod = date + '000'
            date_f = dt.datetime.strptime(date_mod, '%Y%m%d.%H%M').strftime('%Y-%m-%d %H:%M')
        else:
            date_f = dt.datetime.strptime(date, '%Y%m%d.%H%M').strftime('%Y-%m-%d %H:%M')
        dates.append([date_f, date, watershed, subbasin, comid])

    dates.append(['Select Date', dates[-1][1]])
    dates.reverse()

    return JsonResponse({
        "success": "Data analysis complete!",
        "available_dates": json.dumps(dates)
    })


def get_return_periods(request):
    get_data = request.GET

    comid = get_data['comid']

    res = requests.get(
        app.get_custom_setting(
            'api_source') + '/apps/streamflow-prediction-tool/api/GetReturnPeriods/?watershed_name=' +
        watershed + '&subbasin_name=' + subbasin + '&reach_id=' + comid,
        headers={'Authorization': 'Token ' + app.get_custom_setting('spt_token')}, verify=False)

    return eval(res.content)


def get_historic_data(request):
    """""
    Returns ERA Interim hydrograph
    """""

    get_data = request.GET

    try:
        comid = get_data['comid']
        hist = geoglows.streamflow.historic_simulation(comid)
        rperiods = geoglows.streamflow.return_periods(comid)
        title = {'Upstream Drainage Area': get_data['tot_drain_area']}
        return JsonResponse({'plot': geoglows.plots.historic_simulation(
            hist, rperiods, titles=title, outformat='plotly_html')})

    except Exception as e:
        print(str(e))
        return JsonResponse({'error': 'No historic data found for the selected reach.'})


def get_flow_duration_curve(request):
    get_data = request.GET

    try:
        comid = get_data['comid']

        hist = geoglows.streamflow.historic_simulation(comid)
        title = {'Upstream Drainage Area': get_data['tot_drain_area']}
        return JsonResponse({'plot': geoglows.plots.flow_duration_curve(hist, titles=title, outformat='plotly_html')})

    except Exception as e:
        print(str(e))
        return JsonResponse({'error': 'No historic data found for calculating flow duration curve.'})


def get_return_period_ploty_info(request, datetime_start, datetime_end,
                                 band_alt_max=-9999):
    """
    Get shapes and annotations for plotly plot
    """

    # Return Period Section
    return_period_data = get_return_periods(request)
    return_max = float(return_period_data["max"])
    return_20 = float(return_period_data["twenty"])
    return_10 = float(return_period_data["ten"])
    return_2 = float(return_period_data["two"])

    # plotly info section
    shapes = [
        # return 20 band
        dict(
            type='rect',
            xref='x',
            yref='y',
            x0=datetime_start,
            y0=return_20,
            x1=datetime_end,
            y1=max(return_max, band_alt_max),
            line=dict(width=0),
            fillcolor='rgba(128, 0, 128, 0.4)',
        ),
        # return 10 band
        dict(
            type='rect',
            xref='x',
            yref='y',
            x0=datetime_start,
            y0=return_10,
            x1=datetime_end,
            y1=return_20,
            line=dict(width=0),
            fillcolor='rgba(255, 0, 0, 0.4)',
        ),
        # return 2 band
        dict(
            type='rect',
            xref='x',
            yref='y',
            x0=datetime_start,
            y0=return_2,
            x1=datetime_end,
            y1=return_10,
            line=dict(width=0),
            fillcolor='rgba(255, 255, 0, 0.4)',
        ),
    ]
    annotations = [
        # return max
        dict(
            x=datetime_end,
            y=return_max,
            xref='x',
            yref='y',
            text='Max. ({:.1f})'.format(return_max),
            showarrow=False,
            xanchor='left',
        ),
        # return 20 band
        dict(
            x=datetime_end,
            y=return_20,
            xref='x',
            yref='y',
            text='20-yr ({:.1f})'.format(return_20),
            showarrow=False,
            xanchor='left',
        ),
        # return 10 band
        dict(
            x=datetime_end,
            y=return_10,
            xref='x',
            yref='y',
            text='10-yr ({:.1f})'.format(return_10),
            showarrow=False,
            xanchor='left',
        ),
        # return 2 band
        dict(
            x=datetime_end,
            y=return_2,
            xref='x',
            yref='y',
            text='2-yr ({:.1f})'.format(return_2),
            showarrow=False,
            xanchor='left',
        ),
    ]

    return shapes, annotations


def get_historic_data_csv(request):
    """""
    Returns ERA Interim data as csv
    """""

    get_data = request.GET

    try:
        # model = get_data['model']
        watershed = get_data['watershed_name']
        subbasin = get_data['subbasin_name']
        comid = get_data['reach_id']

        era_res = requests.get(
            app.get_custom_setting(
                'api_source') + '/apps/streamflow-prediction-tool/api/GetHistoricData/?watershed_name=' +
            watershed + '&subbasin_name=' + subbasin + '&reach_id=' + comid + '&return_format=csv',
            headers={'Authorization': 'Token ' + app.get_custom_setting('spt_token')}, verify=False)

        qout_data = era_res.content.decode('utf-8').splitlines()
        qout_data.pop(0)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=historic_streamflow_{0}_{1}_{2}.csv'.format(watershed,
                                                                                                            subbasin,
                                                                                                            comid)

        writer = csv_writer(response)

        writer.writerow(['datetime', 'streamflow (m3/s)'])

        for row_data in qout_data:
            writer.writerow(row_data.split(','))

        return response

    except Exception as e:
        print(str(e))
        return JsonResponse({'error': 'No historic data found.'})


def get_forecast_data_csv(request):
    """""
    Returns Forecast data as csv
    """""

    get_data = request.GET

    try:
        # model = get_data['model']
        watershed = get_data['watershed_name']
        subbasin = get_data['subbasin_name']
        comid = get_data['reach_id']
        if get_data['startdate'] != '':
            startdate = get_data['startdate']
        else:
            startdate = 'most_recent'

        res = requests.get(
            app.get_custom_setting('api_source') + '/apps/streamflow-prediction-tool/api/GetForecast/?watershed_name=' +
            watershed + '&subbasin_name=' + subbasin + '&reach_id=' + comid + '&forecast_folder=' +
            startdate + '&return_format=csv',
            headers={'Authorization': 'Token ' + app.get_custom_setting('spt_token')}, verify=False)

        qout_data = res.content.decode('utf-8').splitlines()
        qout_data.pop(0)

        init_time = qout_data[0].split(',')[0].split(' ')[0]
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=streamflow_forecast_{0}_{1}_{2}_{3}.csv'.format(
            watershed,
            subbasin,
            comid,
            init_time)

        writer = csv_writer(response)
        writer.writerow(
            ['datetime', 'high_res (m3/s)', 'max (m3/s)', 'mean (m3/s)', 'min (m3/s)', 'std_dev_range_lower (m3/s)',
             'std_dev_range_upper (m3/s)'])

        for row_data in qout_data:
            writer.writerow(row_data.split(','))

        return response

    except Exception as e:
        print(str(e))
        return JsonResponse({'error': 'No forecast data found.'})


def get_lis_data_csv(request):
    """""
    Returns LIS data as csv
    """""

    get_data = request.GET

    try:
        # model = get_data['model']
        watershed = get_data['watershed_name']
        subbasin = get_data['subbasin_name']
        comid = get_data['reach_id']
        if get_data['startdate'] != '':
            startdate = get_data['startdate']
        else:
            startdate = 'most_recent'

        path = os.path.join(app.get_custom_setting('lis_path'), '-'.join([watershed, subbasin]))
        filename = [f for f in os.listdir(path) if 'Qout' in f]
        res = nc.Dataset(os.path.join(app.get_custom_setting('lis_path'), '-'.join([watershed, subbasin]), filename[0]),
                         'r')

        dates_raw = res.variables['time'][:]
        dates = []
        for d in dates_raw:
            dates.append(dt.datetime.fromtimestamp(d).strftime('%Y-%m-%d %H:%M:%S'))

        comid_list = res.variables['rivid'][:]
        comid_index = int(np.where(comid_list == int(comid))[0])

        values = []
        for l in list(res.variables['Qout'][:]):
            values.append(float(l[comid_index]))

        pairs = [list(a) for a in zip(dates, values)]

        init_time = pairs[0][0].split(' ')[0]
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=lis_streamflow_{0}_{1}_{2}_{3}.csv'.format(watershed,
                                                                                                           subbasin,
                                                                                                           comid,
                                                                                                           init_time)

        writer = csv_writer(response)
        writer.writerow(['datetime', 'flow (m3/s)'])

        for row_data in pairs:
            writer.writerow(row_data)

        return response

    except Exception as e:
        print(str(e))
        return JsonResponse({'error': 'No forecast data found.'})


def get_hiwat_data_csv(request):
    """""
    Returns HIWAT data as csv
    """""

    get_data = request.GET

    try:
        # model = get_data['model']
        watershed = get_data['watershed_name']
        subbasin = get_data['subbasin_name']
        comid = get_data['reach_id']
        if get_data['startdate'] != '':
            startdate = get_data['startdate']
        else:
            startdate = 'most_recent'

        path = os.path.join(app.get_custom_setting('hiwat_path'), '-'.join([watershed, subbasin]))
        filename = [f for f in os.listdir(path) if 'Qout' in f]
        res = nc.Dataset(
            os.path.join(app.get_custom_setting('hiwat_path'), '-'.join([watershed, subbasin]), filename[0]), 'r')

        dates_raw = res.variables['time'][:]
        dates = []
        for d in dates_raw:
            dates.append(dt.datetime.fromtimestamp(d).strftime('%Y-%m-%d %H:%M:%S'))

        comid_list = res.variables['rivid'][:]
        comid_index = int(np.where(comid_list == int(comid))[0])

        values = []
        for l in list(res.variables['Qout'][:]):
            values.append(float(l[comid_index]))

        pairs = [list(a) for a in zip(dates, values)]

        init_time = pairs[0][0].split(' ')[0]
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=hiwat_streamflow_{0}_{1}_{2}_{3}.csv'.format(watershed,
                                                                                                             subbasin,
                                                                                                             comid,
                                                                                                             init_time)

        writer = csv_writer(response)
        writer.writerow(['datetime', 'flow (m3/s)'])

        for row_data in pairs:
            writer.writerow(row_data)

        return response

    except Exception as e:
        print(str(e))
        return JsonResponse({'error': 'No forecast data found.'})


def setDefault(request):
    get_data = request.GET
    set_custom_setting(get_data.get('ws_name'), get_data.get('model_name'))
    return JsonResponse({'success': True})


def get_units_title(unit_type):
    """
    Get the title for units
    """
    units_title = "m"
    if unit_type == 'english':
        units_title = "ft"
    return units_title


def forecastpercent(request):
    # Check if its an ajax post request
    if request.is_ajax() and request.method == 'GET':
        comid = request.GET.get('comid')
        stats = geoglows.streamflow.forecast_stats(comid)
        ensems = geoglows.streamflow.forecast_ensembles(comid)
        rperiods = geoglows.streamflow.return_periods(comid)
        return JsonResponse({'table': geoglows.plots.probabilities_table(stats, ensems, rperiods)})
