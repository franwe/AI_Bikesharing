import pandas as pd
import os
from datetime import datetime, timedelta
import math
import holidays
import numpy as np
import json
import copy
cwd = os.getcwd()
us_holidays = holidays.UnitedStates()

from os import listdir
from os.path import isfile, join

def load_data(path = cwd+'/data/tripdata'):
    """ open and combine all trip data files inside folder
        changes date string to datetime
    """
    files = [f for f in listdir(path) if isfile(join(path, f))]
    files.sort()
    data = pd.read_csv(path+'/'+files[0])

    for file in files[1:]:
        data_month = pd.read_csv(path+'/'+file)
        print(file, data.shape, data_month.shape)
        data = data.append(data_month, ignore_index = True)

    data['starttime'] = pd.to_datetime(data['Start date'], format='%Y-%m-%d %H:%M:%S')
    data['endtime'] = pd.to_datetime(data['End date'], format='%Y-%m-%d %H:%M:%S')

    return data

def sort_in_clusters(data, level, grid_size, suffix=None):
    """ instead of looking at individual stations, create clusters of stations.
        draw grid of size grid_size*grid_size over map and combine all stations that fall into one cell to one cluster
    """
    grid_size = grid_size + 1
    threshold_lats = np.linspace(data.latitude.min(), data.latitude.max(), grid_size)
    threshold_lons = np.linspace(data.longitude.min(), data.longitude.max(), grid_size)

    layers = data[['id', 'latitude', 'longitude']]

    layers['lat'] = 0
    for i in range(1, len(threshold_lats)):
        layers['lat'][layers.latitude > threshold_lats[i]] = i * 100

    layers['lon'] = 0
    for i in range(1, len(threshold_lons)):
        layers['lon'][layers.longitude > threshold_lons[i]] = i
    if level == 'clustering':
        layers['help_id'] = layers.lat + layers.lon
        size = layers.help_id.value_counts()
        id_dict = size.reset_index().reset_index().rename(
            columns={'level_0': 'cluster_id', 'index': 'help_id', 'help_id': 'count'})
        stations_rough = layers.merge(id_dict, how='left', left_on='help_id', right_on='help_id')[['id', 'cluster_id']]
        return stations_rough
    else:
        if level == 1:
            layers['L1'] = layers.apply(lambda x: str(int(x.lat + x.lon)), axis=1)
        else:
            layers['L' + str(level)] = layers.apply(lambda x: str(suffix) + '_' + str(int(x.lat + x.lon)), axis=1)
        return layers[['id', 'L' + str(level)]]

def remerge_clusters(data, cluster_id):
    """ when creating the location clusters L1 and L2, some of the station-clusters got split apart
        this function checks in which L1_L2 location the stations of one cluster lay and then assigns all of the
        stations to the L1_L2 location where the majority of the stations lay.
    """
    subset = data[data.cluster_id == cluster_id]
    if subset.shape[0] > 1:
        total_size = sum(subset.cluster_size)
        L1 = subset['L1'][subset.cluster_size == subset.cluster_size.max()].iloc[0]
        L2 = subset.L2[subset.cluster_size == subset.cluster_size.max()].iloc[0]
        new_row = pd.DataFrame(data=[[cluster_id, total_size, L1, L2]], columns=list(subset.columns))
        return (new_row)
    else:
        return (subset)

def get_stations(path = cwd + '/data/Capital_Bike_Share_Locations.csv'):
    """ creates several files of station information
        stations_rough: id (560 stations)
                        cluster_id (170 clusters),
                        location (latitude, longitude) and
                        artificial location of station (L1, L2)
        cluster_info: cluster_id (170 clusters)
                      cluster_size (19 to 1)
                      artificial location of cluster (L1, L2)
    """
    stations = pd.read_csv(path)
    stations['CAPACITY'] = stations.NUMBER_OF_BIKES + stations.NUMBER_OF_EMPTY_DOCKS
    stations = stations[['TERMINAL_NUMBER', 'LATITUDE', 'LONGITUDE']]
    stations.columns = ['id', 'latitude', 'longitude']

    # clusters
    stations_rough = sort_in_clusters(stations, 'clustering', 32)

    # layers - sub-layers
    # level 1, divide in 4 parts
    layers = sort_in_clusters(stations, level=1, grid_size=4)
    stations = stations.merge(layers, how='left', left_on='id', right_on='id').fillna('0')

    # level 2, take busy clusters from level 1 and divide in 4 parts
    layers_combined = pd.DataFrame(columns=['id', 'L2'])
    for L1_id in ['101', '102', '2', '202']:
        data_subcluster = stations[stations.L1 == L1_id]
        layers = sort_in_clusters(data_subcluster, level=2, grid_size=4, suffix=L1_id)
        layers_combined = pd.concat([layers_combined, layers], join='inner', ignore_index=True)

    layers_combined['id'] = layers_combined.id.apply(lambda x: int(x))  # transform into in, otherwise merge doesnt work
    stations = stations.merge(layers_combined, how='left', left_on='id', right_on='id').fillna('0')

    # expand stations_rough with L1 and L2 information
    stations_rough = stations_rough.merge(stations[['id', 'latitude', 'longitude', 'L1', 'L2']], how='left', left_on='id', right_on='id')
    cluster_size = stations_rough.groupby(by=['cluster_id', 'L1', 'L2']).count().reset_index().rename(columns={'id': 'cluster_size'})[
        ['cluster_id', 'cluster_size', 'L1', 'L2']]

    cluster_info = pd.DataFrame(columns=cluster_size.columns)
    for i in range(0, cluster_size.cluster_id.max()):
        new_row = remerge_clusters(cluster_size, i)
        cluster_info = pd.concat([cluster_info, new_row], ignore_index=True)

    cluster_info['cluster_id'] = cluster_info.cluster_id.apply(lambda x: int(x))

    return stations_rough, cluster_info

def load_weatherdata(path=cwd + '/data/weatherdata.json'):
    """ loads the weather data and transforms date string into datetime """
    with open(path) as json_file:
        weather = json.load(json_file)
    weather_df = pd.DataFrame(weather['observations'])
    weather_df['datetime'] = pd.to_datetime(weather_df['time_gmt'], format='%Y-%m-%d %H:%M:%S')
    return weather_df

def clean_weatherdata(weatherdata):
    """ cleaning of weather data, had 56 weather phrases, that are now described by only 7 variables"""
    phrases = weatherdata.phrase.value_counts()
    phrases = phrases.reset_index()

    phrases['wind'] = phrases['index'].apply(lambda x: int('Windy' in x))

    winter = ['Wintry', 'Snow', 'Freezing', 'Sleet']
    thunder = ['T-', 'Thunder', 'Squalls']
    extreme = ['Heavy', 'T-Storm', 'Thunder', 'Squalls']

    phrases['wintry'] = phrases['index'].apply(lambda x: int(any([term in x for term in winter])))
    phrases['thunderstorm'] = phrases['index'].apply(lambda x: int(any([term in x for term in thunder])))
    phrases['extreme_weather'] = phrases['index'].apply(lambda x: int(any([term in x for term in extreme])))

    light_rain = ['Light Rain', 'Light Drizzle', 'Light Freezing Rain']  # give 1
    heavy_rain = ['Rain', 'Heavy Rain']  # give 2, do this first because otherwise would overwrite 'Light Rain'
    foggy = ['Fog', 'Mist', 'Haze']
    clear_sky = ['Fair', 'Partly Cloudy']  # give 1

    phrases['foggy'] = phrases['index'].apply(lambda x: int(any([term in x for term in foggy])))

    phrases['rain'] = 0
    phrases['rain'][phrases['index'].apply(lambda x: any([term in x for term in heavy_rain]))] = 2
    phrases['rain'][phrases['index'].apply(lambda x: any([term in x for term in light_rain]))] = 1

    phrases['clear_sky'] = phrases['index'].apply(lambda x: int(any([term in x for term in clear_sky])))
    phrases = phrases.drop(columns='phrase')
    phrases.rename(columns={'index': 'phrase'}, inplace=True)

    return phrases

def yearly_data(data, year, time_str):
    """ retrieves subset of only current year from whole dataset to make lookup faster """
    print(data.shape, year)
    start = datetime(year=year-1, month=12, day=31, hour=20, minute=0)  # a few hours before, because of return offset
    end = datetime(year=year+1, month=1, day=1, hour=0, minute=0)
    data_year = data[(data[time_str] >= start) & (data[time_str] < end)]
    print('have data from: ', start, ' to ', end, data_year.shape)
    return data_year

def tripdata_to_station(action, startdate, enddate, data, stations_rough, cluster_size, weatherdata, weather_phrases):
    """ From startdate to enddate, create dataframe of pickups or returns (which action) that happened within the next
        90 minutes window at this cluster.
        Also create attributes that we use for building the trees and prediction:
        time, weekday, holiday, month, weather
        return: dataframe of pickups/returns at clusters during 90 minutes range with special information
    """
    # within next 90 minutes will have x actions at station
    delta = timedelta(minutes=90)
    time = startdate

    if action == 'pickups':
        action_str, time_str = 'pickups', 'starttime'
        data_column = 'Start station number'
    elif action == 'returns':
        action_str, time_str = 'returns', 'endtime'
        data_column = 'End station number'
    else:
        print('wrong action type, choose pickups or returns')

    data = data[[time_str, data_column]]
    data_s = stations_rough.merge(data, how='right', left_on='id', right_on=data_column)[[time_str, 'cluster_id']]

    actions_combined = pd.read_pickle(cwd+'/data/' + action_str + '_' + 'empty.pkl')
    step = 1

    first_year = startdate.year
    current_year = first_year
    data_year = yearly_data(data_s, first_year, time_str)

    while time < enddate:
        print(time, time + delta, current_year)

        if time.year == current_year + 1:

            # final save of data from last year
            cols = list(actions_combined.columns)
            cols.remove(action_str)
            cols.append(action_str)
            actions_combined = actions_combined[cols]

            actions_combined.to_pickle(cwd + '/data/' + action_str + '_' +  str(current_year) + '.pkl')
            actions_combined.to_csv(cwd + '/data/' + action_str + '_' +  str(current_year) + '.csv')

            # get data for next year
            current_year += 1
            print('--------------- next year, use data for ', current_year)
            data_year = yearly_data(data_s, current_year, time_str)

            actions_combined = pd.read_pickle(cwd + '/data/' + action_str + '_' + 'empty.pkl')

        if action == 'pickups':
            actions = data_year[(data_year[time_str] >= time) &
                             (data_year[time_str] < time + delta)].groupby(['cluster_id']).count()
        elif action == 'returns':  # offset of 30 minutes before pickups
            actions = data_year[(data_year[time_str] >= time - timedelta(minutes=30)) &
                             (data_year[time_str] < time + delta - timedelta(minutes=30))].groupby(['cluster_id']).count()

        # multi-index to single index and rename columns
        actions = actions.reset_index()
        actions.rename(columns={time_str: action_str}, inplace=True)
        actions = cluster_size.merge(actions, how='left', left_on='cluster_id', right_on='cluster_id').fillna(0)
        #
        # # cluster size
        # actions = actions.merge(cluster_size, how='left')

        actions['holiday'] = int(time in us_holidays)
        actions['weekday'] = time.weekday()
        actions['datetime'] = time
        actions['time'] = time.time()
        actions['month'] = time.month

        # weather data
        try:
            current_weather = weatherdata[(weatherdata.datetime >= time - timedelta(minutes=30)) &
                                         (weatherdata.datetime < time + timedelta(minutes=29))].iloc[0]
        except IndexError:
            print('use last available weather information')
            pass

        actions['phrase'] = current_weather['phrase']
        actions['temperature'] = current_weather['temp']
        actions['humidity'] = current_weather['humidity']
        actions = actions.merge(weather_phrases, how='left')
        actions = actions.drop(columns='phrase')

        # temperature and humidity ranges
        threshold_temps = [30, 40, 50, 60, 70, 80]
        actions['temp'] = 0
        for i in range(0, len(threshold_temps)):
            actions['temp'][actions.temperature >= threshold_temps[i]] = threshold_temps[i]

        threshold_hums = [40, 50, 60, 70, 80, 90]
        actions['hum'] = 0
        for i in range(0, len(threshold_hums)):
            actions['hum'][actions.humidity >= threshold_hums[i]] = threshold_hums[i]

        actions_combined = pd.concat([actions_combined, actions], ignore_index=True)

        if not (step%50):
            print(step, ' save csv and pkl')
            actions_combined.to_pickle(cwd + '/data/' + action_str + '_' +  str(current_year) + '.pkl')
            actions_combined.to_csv(cwd + '/data/' + action_str + '_' +  str(current_year) + '.csv')

        time += delta
        step += 1
    # final save of data

    cols = list(actions_combined.columns)
    cols.remove(action_str)
    cols.append(action_str)
    actions_combined = actions_combined[cols]

    actions_combined.to_pickle(cwd + '/data/' + action_str + '_' +  str(current_year) + '.pkl')
    actions_combined.to_csv(cwd + '/data/' + action_str + '_' +  str(current_year) + '.csv')

    return actions_combined

def ceil_or_floor(x):
    """ round negative numbers down (-3.5 --> -4) and positive numbers up (3.5 --> 4) """
    if x <= 0:
        return math.floor(x)
    elif x > 0:
        return math.ceil(x)

def demand(pickups, returns, year):
    """ combine pickups and returns from tripdata_to_station to demand = returns - pickups
        calculate relative demand, which is demand on cluster divided by cluster_size
    """
    pickups['rel_pickups'] = pickups.pickups / pickups.cluster_size
    returns['rel_returns'] = returns.returns / returns.cluster_size

    results = copy.deepcopy(returns)
    results['rel'] = returns.rel_returns - pickups.rel_pickups
    results['demand'] = results['rel'].apply(lambda x: ceil_or_floor(x))


    results = results[['cluster_id', 'L1', 'L2',
                       'weekday', 'holiday', 'time',
                       'month', 'clear_sky', 'extreme_weather',
                       'hum', 'rain', 'temp',
                       'wind', 'wintry', 'demand']]
    results.to_csv(cwd + '/data/results_' + str(year) + '.csv')
    # results.to_pickle(cwd + '/data/results_' + str(year) + '.pkl')
    return results

def combine_all_results(years):
    year = years[0]
    data = pd.read_pickle(cwd+'/data/results_' + str(year) + '.pkl')

    for i in range(1,len(years)):
        year = years[i]
        print(year)
        data_new = pd.read_pickle(cwd + '/data/results_' + str(year) + '.pkl')
        print(data.shape, data_new.shape)
        data = pd.concat([data, data_new], ignore_index=True)

    print('save file')
    data.to_csv(cwd + '/data/results_all.csv')
    data.to_pickle(cwd + '/data/results_all.pkl')


if __name__ == "__main__":

    years = [2017, 2018, 2019]

    print('--------tripdata------')
    data = load_data()
    data.to_pickle(cwd+'/data/tripdata_2017-now.pkl')
    data = pd.read_pickle(cwd+'/data/tripdata_2017-now.pkl')

    print('-------stations--------')
    stations_info, cluster_info = get_stations()

    print('----------weather--------')
    weatherdata = load_weatherdata()
    weather_phrases = clean_weatherdata(weatherdata)

    for year in years:

        startdate = datetime(year=year, month=1, day=1, hour=0, minute=0)
        enddate = datetime(year=year+1, month=1, day=1, hour=0, minute=0)

        print('---------tripdata-to-stations---------')
        tripdata_to_station('pickups', startdate, enddate, data, stations_info, cluster_info, weatherdata, weather_phrases)

        print('---------tripdata-to-returns---------')
        tripdata_to_station('returns', startdate, enddate, data, stations_info, cluster_info, weatherdata, weather_phrases)

    print('--------demand--------')
    for year in years:
        print(year)
        pickups = pd.read_pickle(cwd + '/data/pickups_' + str(year) + '.pkl')
        returns = pd.read_pickle(cwd + '/data/returns_' + str(year) + '.pkl')
        demand(pickups, returns, year)

    print('-------combine results------')
    combine_all_results(years)