class FavoriteCompany {
  const FavoriteCompany({required this.companyId, required this.companyName});

  final int companyId;
  final String companyName;

  factory FavoriteCompany.fromJson(Map<String, dynamic> json) {
    return FavoriteCompany(
      companyId: json['company_id'] as int,
      companyName: (json['company_name'] ?? '') as String,
    );
  }
}
