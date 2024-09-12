from datetime import datetime
from typing import List, Optional, Tuple
import requests
from bs4 import BeautifulSoup
import time
import pandas as pd
import random
from .utils import (
  normalize_name, 
  handle_http_error, 
  handle_general_error,
  filter_relevant_months,
  )
from .config.variables import BASE_URL, TEAM_ABBREVIATIONS


def get_month_links(season: str) -> Optional[Tuple[List[Tuple[str, str]], int, int]]:
  """
  Fetches the month links from the Basketball Reference website for a given NBA season.

  Inputs:
    season (str): The NBA season in the format 'YYYY-YY' (e.g., '2019-20').

  Returns:
    tuple: A tuple containing:
      - month_link_list (list of tuples): A list of tuples where each tuple contains:
        - name of the month (str): The name of the month (e.g., 'october', 'november').
        - url (str): The full URL to the page for that month.
  """
  try:
    start_year, end_year = season.split('-') # 2021-22
    start_year_full = int(start_year)
    if len(end_year) != 2 or not end_year.isdigit():
      raise ValueError
  except(ValueError, AttributeError):
    print(f"Invalid season format: {season}. Expected format is 'YYYY-YY'.")
    return None, None

  end_year_full = start_year_full + 1 if end_year == '00' else int(str(start_year_full)[:2] + end_year)
  
  start_url = f"{BASE_URL}/leagues/NBA_{end_year_full}_games.html"

  month_link_list = []
  try:
    response = requests.get(start_url)
    response.raise_for_status()
  except requests.exceptions.HTTPError:
    handle_http_error(response)
  except Exception as e:
    handle_general_error(e, start_url)
  
  soup = BeautifulSoup(response.text, 'html.parser')
  body = soup.find('body')

  div_elements = body.find_all('div', class_='filter')
  for div in div_elements:
    a_tags = div.find_all('a', href=True)
    for a_tag in a_tags:
      link_text = a_tag.text.strip().lower()
      if any(month in link_text for month in a_tag.text.strip().lower().split()):
        month_link_list.append((link_text, f"{BASE_URL}{a_tag['href']}"))
    
  return month_link_list, start_year_full, end_year_full


def get_box_score_links(month_link_list: List[Tuple[str, str]], 
                        start_date: Optional[str], 
                        end_date: Optional[str],
                        start_year: int,
                        end_year: int,
                        ) -> Tuple[Optional[List[List[str]]], Optional[List[List[str]]]]:
  """
  Fetches box score links and corresponding game dates within a given date range (for batch scraping).

  Inputs:
    month_link_list (list of tuples): List of tuples where each tuple contains:
      - month (str): The name of the month (e.g., 'october').
      - page (str): The full URL to the page for that month.
    start_data: The start date for filtering games (format: YYYY-MM-DD)
    end_date: The end date for filtering games (format: YYYY-MM-DD)

    empty start_date and end_date defaults to current season date range.

  Returns:
    tuple: A tuple containing:
      - box_link_array (list of lists): A list of lists where each inner list contains the URLs to box scores for the games played in the given date range.
      - all_dates (list of lists): A list of lists where each inner list contains the corresponding dates (formatted as 'YYYYMMDD') for the box scores in the same order as `box_link_array`.
  """
  start_date_dt = datetime.strptime(start_date, '%Y-%m-%d')
  end_date_dt = datetime.strptime(end_date, '%Y-%m-%d')
    
  if start_date_dt > end_date_dt:
    raise ValueError("Start date cannot be after end date.")

  relevant_month_link_list = filter_relevant_months(month_link_list, start_date_dt, end_date_dt, start_year, end_year) 
  
  box_link_array = []
  all_dates = []

  for _, page in relevant_month_link_list:
    page_link_list = []
    page_date_list = []
    try:
      response = requests.get(page)
      response.raise_for_status()
      soup = BeautifulSoup(response.text, 'html.parser')

      rows = soup.find_all('tr')
      for row in rows:
        date_cell = row.find('th', attrs={'data-stat': 'date_game'})
        if date_cell and date_cell.has_attr('csk'):
          game_date_str = date_cell['csk'][:8]
          game_date_dt = datetime.strptime(game_date_str, '%Y%m%d')

          if (start_date_dt and end_date_dt) and not (start_date_dt <= game_date_dt <= end_date_dt):
            continue

          box_score_cell = row.find('td', attrs={'data-stat': 'box_score_text'})
          if box_score_cell and box_score_cell.find('a', href=True):
            box_score_link = f"{BASE_URL}{box_score_cell.find('a')['href']}"
            page_link_list.append(box_score_link)
            page_date_list.append(game_date_dt.strftime('%Y-%m-%d'))

      if page_link_list:
        box_link_array.append(page_link_list)
        all_dates.append(page_date_list)
      time.sleep(random.uniform(0.5, 2))

    except requests.exceptions.HTTPError:
      handle_http_error(response)
    except Exception as e:
      handle_general_error(e, page)

  return box_link_array, all_dates


# from https://medium.com/@HeeebsInc/using-machine-learning-to-predict-daily-fantasy-basketball-scores-part-i-811de3c54a98
def extract_player_data(box_links: List[List[str]], 
                        all_dates: List[List[str]]
                        ) -> pd.DataFrame:
  """
  Extract player statistics from each box score link and save the data to a DataFrame.

  Inputs:
    box_links (list of lists): A list containing lists of URLs to box score pages.
    all_dates (list of lists): A list containing lists of dates corresponding to the box scores.

  Returns:
    stat_df (pd.DataFrame): A DataFrame containing the extracted player statistics.
  """
  df_columns = [
                'Date', 'Name', 'Team', 'Opponent', 'MP', 'FG', 'FGA', 'FG%', '3P', '3PA',
                '3P%','FT', 'FTA', 'FT%', 'ORB','DRB', 'TRB', 'AST', 'STL', 'BLK', 
                'TOV', 'PF', 'PTS', 'GmSc', '+-', 'GameLink', 'Home'
               ]
  
  stat_df = pd.DataFrame(columns=df_columns)

  for i, (links, dates) in enumerate(zip(box_links, all_dates)):
    print(f'Processing batch {i+1}/{len(box_links)}')

    for link, date in zip(links, dates):
      print(f'Scraping box score: {link} for game date {date}')
      
      try:
        response = requests.get(link)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')

        home_team_abbr = link.split('/')[-1].split('.')[0][-3:]  # e.g. https://www.basketball-reference.com/boxscores/202310240DEN.html
        home_team = TEAM_ABBREVIATIONS.get(home_team_abbr, None)

        tables = soup.find_all('table', id=lambda x: x and x.endswith('-game-basic'))
        team_names = [table.find('caption').text.split(' Basic and Advanced Stats Table')[0].strip() for table in tables]
        for table in tables:
          team_name = table.find('caption').text.split(' Basic and Advanced Stats Table')[0].strip()
          opponent_name = team_names[1] if team_names[0] == team_name else team_names[0]
          rows = table.find('tbody').find_all('tr')

          is_home = 1 if team_name == home_team else 0

          for row in rows:
            if row.find('th').text in ['Team Totals', 'Reserves']:
              continue
            player_name = normalize_name(row.find('th').text.strip())

            stats = [date, player_name, team_name, opponent_name]

            dnp = row.find('td', {'data-stat': 'reason'})
            if dnp and 'Did Not Play' in dnp.text:
              stats += ['DNP'] * (len(df_columns) - 6)
            else:
              for td in row.find_all('td'):
                stats.append(td.text.strip() or '0')
            
            stats.append(link)
            stats.append(is_home)

            if len(stats) == len(df_columns):
              new_row = pd.DataFrame([stats], columns=df_columns)
              stat_df = pd.concat([stat_df, new_row], ignore_index=True)
            else:
              print(f'Skipping incomplete data for {player_name}')

      except requests.exceptions.HTTPError:
        handle_http_error(response)
      except Exception as e:
        handle_general_error(e, link)
      
      time.sleep(random.uniform(3, 7))

  return stat_df
