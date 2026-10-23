from django.db import models


class Product(models.Model):
    product_id = models.AutoField(primary_key=True)
    category_id = models.IntegerField()
    name = models.CharField(max_length=150)
    description = models.CharField(max_length=255, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        managed = False
        db_table = "products"

    def __str__(self):
        return self.name