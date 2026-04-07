import 'package:flutter/material.dart';

import '../../../core/network/api_client.dart';
import '../../../shared/models/favorite_company.dart';

class FavoritesPage extends StatefulWidget {
  const FavoritesPage({this.embedded = false, this.refreshToken = 0, super.key});

  final bool embedded;
  final int refreshToken;

  @override
  State<FavoritesPage> createState() => _FavoritesPageState();
}

class _FavoritesPageState extends State<FavoritesPage> {
  final ApiClient _apiClient = ApiClient();

  bool _loading = true;
  String? _error;
  List<FavoriteCompany> _companies = const [];

  @override
  void initState() {
    super.initState();
    _loadFavorites();
  }

  @override
  void didUpdateWidget(covariant FavoritesPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.refreshToken != oldWidget.refreshToken) {
      _loadFavorites();
    }
  }

  Future<void> _loadFavorites() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final companies = await _apiClient.fetchFavoriteCompanies();
      if (!mounted) {
        return;
      }
      setState(() {
        _companies = companies;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _error = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final body = _buildBody();
    if (widget.embedded) {
      return body;
    }
    return Scaffold(appBar: AppBar(title: const Text('收藏')), body: body);
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(onPressed: _loadFavorites, child: const Text('重试')),
            ],
          ),
        ),
      );
    }

    if (_companies.isEmpty) {
      return const Center(child: Text('暂无收藏企业'));
    }

    return RefreshIndicator(
      onRefresh: _loadFavorites,
      child: ListView.separated(
        itemCount: _companies.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final company = _companies[index];
          return ListTile(
            leading: const CircleAvatar(child: Icon(Icons.business)),
            title: Text(company.companyName),
            subtitle: Text('企业ID: ${company.companyId}'),
          );
        },
      ),
    );
  }
}
