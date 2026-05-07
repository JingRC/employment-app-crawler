import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../../shared/models/favorite_company.dart';
import '../../shared/models/favorite_job.dart';
import '../../shared/models/job_detail.dart';
import '../../shared/models/job_list_result.dart';
import '../../shared/models/job_timeline_result.dart';
import '../../shared/models/notification_item.dart';
import '../../shared/models/notification_stats.dart';
import '../../shared/models/saved_search_item.dart';

class ApiClient {
  ApiClient({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  String get _baseUrl {
    if (!kIsWeb && Platform.isAndroid) {
      return 'http://10.0.2.2:8000/api';
    }
    return 'http://127.0.0.1:8000/api';
  }

  Future<JobListResult> fetchJobs({
    String keyword = '',
    String cityName = '',
    int page = 1,
    int pageSize = 20,
  }) async {
    final uri = Uri.parse('$_baseUrl/jobs').replace(
      queryParameters: <String, String>{
        if (keyword.trim().isNotEmpty) 'keyword': keyword.trim(),
        if (cityName.trim().isNotEmpty) 'city_name': cityName.trim(),
        'page': '$page',
        'page_size': '$pageSize',
      },
    );
    final response = await _client.get(uri);
    final data = _decodeResponse(response);
    return JobListResult.fromJson(data['data'] as Map<String, dynamic>);
  }

  Future<JobDetail> fetchJobDetail(int jobId) async {
    final response = await _client.get(Uri.parse('$_baseUrl/jobs/$jobId'));
    final data = _decodeResponse(response);
    return JobDetail.fromJson((data['data'] as Map<String, dynamic>));
  }

  Future<void> favoriteJob({required int jobId}) async {
    final response = await _client.post(
      Uri.parse('$_baseUrl/favorites/jobs'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode(<String, dynamic>{'job_id': jobId}),
    );
    _decodeResponse(response);
  }

  Future<List<FavoriteCompany>> fetchFavoriteCompanies() async {
    final response = await _client.get(Uri.parse('$_baseUrl/favorites/companies'));
    final data = _decodeResponse(response);
    final items = (data['data']['items'] as List<dynamic>? ?? <dynamic>[])
        .cast<Map<String, dynamic>>();
    return items.map(FavoriteCompany.fromJson).toList();
  }

  Future<List<FavoriteJob>> fetchFavoriteJobs() async {
    final response = await _client.get(Uri.parse('$_baseUrl/favorites/jobs'));
    final data = _decodeResponse(response);
    final items = (data['data']['items'] as List<dynamic>? ?? <dynamic>[])
        .cast<Map<String, dynamic>>();
    return items.map(FavoriteJob.fromJson).toList();
  }

  Future<bool> unfavoriteJob(int jobId) async {
    final response = await _client.delete(Uri.parse('$_baseUrl/favorites/jobs/$jobId'));
    final data = _decodeResponse(response);
    return (data['data'] ?? false) as bool;
  }

  Future<FavoriteCompany> favoriteCompany({
    required int companyId,
    required String companyName,
  }) async {
    final response = await _client.post(
      Uri.parse('$_baseUrl/favorites/companies'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode(
        <String, dynamic>{
          'company_id': companyId,
          'company_name': companyName,
        },
      ),
    );
    final data = _decodeResponse(response);
    return FavoriteCompany.fromJson(data['data'] as Map<String, dynamic>);
  }

  Future<List<NotificationItem>> fetchNotifications() async {
    final response = await _client.get(Uri.parse('$_baseUrl/notifications'));
    final data = _decodeResponse(response);
    final items = (data['data']['items'] as List<dynamic>? ?? <dynamic>[])
        .cast<Map<String, dynamic>>();
    return items.map(NotificationItem.fromJson).toList();
  }

  Future<List<SavedSearchItem>> fetchSavedSearches() async {
    final response = await _client.get(Uri.parse('$_baseUrl/saved-searches'));
    final data = _decodeResponse(response);
    final items = (data['data']['items'] as List<dynamic>? ?? <dynamic>[])
        .cast<Map<String, dynamic>>();
    return items.map(SavedSearchItem.fromJson).toList();
  }

  Future<SavedSearchItem> createSavedSearch({
    required String keyword,
    required String cityName,
    Map<String, dynamic> filters = const <String, dynamic>{},
    bool enabled = true,
    String notifyFrequency = 'daily',
  }) async {
    final response = await _client.post(
      Uri.parse('$_baseUrl/saved-searches'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode(<String, dynamic>{
        'keyword': keyword,
        'city_name': cityName,
        'filters': filters,
        'enabled': enabled,
        'notify_frequency': notifyFrequency,
      }),
    );
    final data = _decodeResponse(response);
    return SavedSearchItem.fromJson(data['data'] as Map<String, dynamic>);
  }

  Future<SavedSearchItem> updateSavedSearch({
    required int searchId,
    bool? enabled,
  }) async {
    final response = await _client.patch(
      Uri.parse('$_baseUrl/saved-searches/$searchId'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode(<String, dynamic>{
        if (enabled != null) 'enabled': enabled,
      }),
    );
    final data = _decodeResponse(response);
    return SavedSearchItem.fromJson(data['data'] as Map<String, dynamic>);
  }

  Future<bool> deleteSavedSearch(int searchId) async {
    final response = await _client.delete(Uri.parse('$_baseUrl/saved-searches/$searchId'));
    final data = _decodeResponse(response);
    return (data['data'] ?? false) as bool;
  }

  Future<NotificationStats> fetchNotificationStats() async {
    final response = await _client.get(Uri.parse('$_baseUrl/notifications/stats'));
    final data = _decodeResponse(response);
    return NotificationStats.fromJson(data['data'] as Map<String, dynamic>);
  }

  Future<int> markAllNotificationsRead() async {
    final response = await _client.post(Uri.parse('$_baseUrl/notifications/read-all'));
    final data = _decodeResponse(response);
    return (data['data']['affected'] ?? 0) as int;
  }

  Future<bool> markNotificationRead(int notificationId) async {
    final response = await _client.post(Uri.parse('$_baseUrl/notifications/$notificationId/read'));
    final data = _decodeResponse(response);
    return (data['data'] ?? false) as bool;
  }

  Future<JobTimelineResult> fetchJobTimeline(int jobId, {int limit = 10}) async {
    final response = await _client.get(
      Uri.parse('$_baseUrl/notifications/jobs/$jobId?limit=$limit'),
    );
    final data = _decodeResponse(response);
    return JobTimelineResult.fromJson(data['data'] as Map<String, dynamic>);
  }

  Map<String, dynamic> _decodeResponse(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw HttpException('Request failed with status ${response.statusCode}');
    }
    final body = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    if ((body['code'] ?? -1) != 0) {
      throw StateError((body['message'] ?? 'unknown error') as String);
    }
    return body;
  }
}
