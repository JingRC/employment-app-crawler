import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../../shared/models/favorite_company.dart';
import '../../shared/models/job_detail.dart';
import '../../shared/models/job_item.dart';
import '../../shared/models/job_list_result.dart';
import '../../shared/models/notification_item.dart';

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

  Future<List<FavoriteCompany>> fetchFavoriteCompanies() async {
    final response = await _client.get(Uri.parse('$_baseUrl/favorites/companies'));
    final data = _decodeResponse(response);
    final items = (data['data']['items'] as List<dynamic>? ?? <dynamic>[])
        .cast<Map<String, dynamic>>();
    return items.map(FavoriteCompany.fromJson).toList();
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
