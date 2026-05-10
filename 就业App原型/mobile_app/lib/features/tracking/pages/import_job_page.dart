import 'package:flutter/material.dart';

import '../../../core/network/api_client.dart';

class ImportJobPage extends StatefulWidget {
  const ImportJobPage({this.initialUrl = '', super.key});

  final String initialUrl;

  @override
  State<ImportJobPage> createState() => _ImportJobPageState();
}

class _ImportJobPageState extends State<ImportJobPage> {
  final ApiClient _apiClient = ApiClient();
  final _urlController = TextEditingController();
  final _titleController = TextEditingController();
  final _companyController = TextEditingController();
  final _cityController = TextEditingController();
  final _salaryController = TextEditingController();
  final _notesController = TextEditingController();

  bool _submitting = false;
  String? _detectedPlatform;

  @override
  void initState() {
    super.initState();
    _urlController.text = widget.initialUrl;
    if (widget.initialUrl.isNotEmpty) {
      _detectPlatform(widget.initialUrl);
    }
  }

  @override
  void dispose() {
    _urlController.dispose();
    _titleController.dispose();
    _companyController.dispose();
    _cityController.dispose();
    _salaryController.dispose();
    _notesController.dispose();
    super.dispose();
  }

  void _detectPlatform(String url) {
    final detected = ApiClient.detectPlatformFromUrl(url);
    setState(() {
      _detectedPlatform = detected;
    });
  }

  Future<void> _submit() async {
    final title = _titleController.text.trim();
    final company = _companyController.text.trim();
    if (title.isEmpty || company.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('职位名称和公司名称为必填')),
      );
      return;
    }

    setState(() => _submitting = true);
    try {
      final result = await _apiClient.importJob(
        url: _urlController.text.trim(),
        title: title,
        companyName: company,
        cityName: _cityController.text.trim(),
        salaryText: _salaryController.text.trim(),
        notes: _notesController.text.trim(),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('已导入: ${result.title} → 可前往"投递"标签查看')),
      );
      Navigator.of(context).pop(true);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('导入失败: $error')),
      );
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('导入职位')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _urlController,
              decoration: InputDecoration(
                labelText: '职位链接',
                hintText: '粘贴来自Boss直聘/智联/猎聘等的职位链接',
                border: const OutlineInputBorder(),
                suffixIcon: _detectedPlatform != null
                    ? Padding(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        child: Chip(label: Text(_detectedPlatform!)),
                      )
                    : null,
              ),
              onChanged: (value) {
                if (value.trim().isNotEmpty) {
                  _detectPlatform(value.trim());
                } else {
                  setState(() => _detectedPlatform = null);
                }
              },
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(
                labelText: '职位名称 *',
                hintText: '例: Java开发工程师',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _companyController,
              decoration: const InputDecoration(
                labelText: '公司名称 *',
                hintText: '例: 阿里巴巴',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _cityController,
                    decoration: const InputDecoration(
                      labelText: '城市',
                      hintText: '例: 北京',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextField(
                    controller: _salaryController,
                    decoration: const InputDecoration(
                      labelText: '薪资',
                      hintText: '例: 15-25K',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _notesController,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: '备注',
                hintText: '记录投递计划、沟通要点等',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              height: 48,
              child: FilledButton(
                onPressed: _submitting ? null : _submit,
                child: _submitting
                    ? const SizedBox(
                        width: 20, height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Text('保存并开始跟踪', style: TextStyle(fontSize: 16)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
