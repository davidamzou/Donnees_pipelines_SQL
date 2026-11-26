"""M4 · Pipeline PySpark : trajets Yellow 2024-01 enrichis par la table de zones TLC.

Étapes : lecture JSONL + CSV, inspection des schémas, typage explicite, filtrage
qualité, variable calculée (vitesse moyenne), contrôle de la clé de jointure,
détection des non-appariements, jointure sans multiplication, agrégations,
partitionnement et explain(), export Parquet dans un dossier inédit, relecture.

Usage (depuis novamarket/) :
  python volumetrie/spark/pipeline.py volumetrie/data/sorties/essai-$(date +%Y%m%d-%H%M%S)
  python volumetrie/spark/pipeline.py --entree volumetrie/secours/trajets_fictifs.jsonl /tmp/s5_secours_1
Le dossier de sortie ne doit pas exister : aucun résultat antérieur n'est écrasé.
"""
import argparse
import sys
from pathlib import Path

from pyspark.sql import SparkSession, functions as F, types as T

RACINE = Path(__file__).resolve().parents[1]
DISTANCE_MAX_MILES, DUREE_MAX_SECONDES, VITESSE_MAX_MPH = 100, 6 * 3600, 80

SCHEMA_TRAJETS = T.StructType([
    T.StructField("ligne_source", T.LongType()),
    T.StructField("Start_Zone", T.LongType()),
    T.StructField("Trip_Distance", T.DoubleType()),
    T.StructField("Trip_Duration", T.LongType()),
    T.StructField("_corrupt_record", T.StringType()),
])


def titre(texte):
    print(f"\n=== {texte} ===")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sortie", type=Path, help="Dossier de sortie Parquet (inexistant)")
    parser.add_argument("--entree", type=Path, default=RACINE / "data" / "spark" / "trajets_controles.jsonl")
    parser.add_argument("--zones", type=Path, default=RACINE / "secours" / "zones.csv")
    args = parser.parse_args()
    if args.sortie.exists():
        sys.exit(f"Refus : {args.sortie} existe déjà ; choisir un dossier de sortie neuf.")

    spark = (SparkSession.builder.master("local[2]").appName("s5-trajets-zones")
             .config("spark.sql.shuffle.partitions", "4")
             .config("spark.sql.session.timeZone", "UTC")
             .config("spark.ui.showConsoleProgress", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    try:
        executer(spark, args)
    finally:
        spark.stop()


def executer(spark, args):
    titre("1. Lecture et inspection des schémas")
    print("Entrée :", args.entree)
    infere = spark.read.json(str(args.entree))
    print("Schéma inféré par Spark (non retenu : types déduits d'un échantillon) :")
    infere.printSchema()
    brut = (spark.read.schema(SCHEMA_TRAJETS)
            .option("mode", "PERMISSIVE").option("columnNameOfCorruptRecord", "_corrupt_record")
            .json(str(args.entree)))
    print("Schéma imposé à la lecture :")
    brut.printSchema()
    zones_brutes = spark.read.option("header", True).csv(str(args.zones))  # tout en chaîne
    zones_brutes.printSchema()

    titre("2. Typage et contrôle des valeurs manquantes")
    brut = brut.cache()
    n_lues = brut.count()
    n_corrompues = brut.where(F.col("_corrupt_record").isNotNull()).count()
    trajets = (brut.where(F.col("_corrupt_record").isNull())
               .select(F.coalesce("ligne_source", F.monotonically_increasing_id()).alias("ligne_source"),
                       F.col("Start_Zone").cast("int").alias("zone_depart"),
                       F.col("Trip_Distance").alias("distance_miles"),
                       F.col("Trip_Duration").cast("int").alias("duree_s")))
    manquants = trajets.select([F.sum(F.col(c).isNull().cast("int")).alias(c)
                                for c in ("zone_depart", "distance_miles", "duree_s")]).first().asDict()
    print(f"Lignes lues : {n_lues} · lignes JSON corrompues : {n_corrompues}")
    print("Valeurs manquantes par colonne :", manquants)
    trajets.printSchema()

    zones = zones_brutes.select(F.col("LocationID").cast("int").alias("zone_id"),
                                F.col("Borough").alias("arrondissement"),
                                F.col("Zone").alias("zone"),
                                F.col("service_zone"))

    titre("3. Filtrage qualité et variable calculée")
    valides = (trajets
               .where(F.col("zone_depart").isNotNull() & F.col("distance_miles").isNotNull()
                      & F.col("duree_s").isNotNull())
               .where((F.col("distance_miles") > 0) & (F.col("distance_miles") <= DISTANCE_MAX_MILES))
               .where((F.col("duree_s") > 0) & (F.col("duree_s") <= DUREE_MAX_SECONDES))
               .withColumn("vitesse_mph", F.col("distance_miles") / (F.col("duree_s") / 3600.0))
               .where(F.col("vitesse_mph") <= VITESSE_MAX_MPH)
               .cache())
    n_valides = valides.count()
    print(f"Avant filtrage : {n_lues - n_corrompues} · après filtrage : {n_valides} "
          f"· écartées : {n_lues - n_corrompues - n_valides}")
    print("Règles : 0 < distance <= 100 mi ; 0 < durée <= 21 600 s ; vitesse = distance / (durée/3600) <= 80 mph")

    titre("4. Contrôle de la clé de la table de zones")
    cle = zones.agg(F.count("*").alias("lignes"), F.countDistinct("zone_id").alias("cles_distinctes"),
                    F.sum(F.col("zone_id").isNull().cast("int")).alias("cles_nulles")).first()
    print(f"Zones : {cle.lignes} lignes, {cle.cles_distinctes} clés distinctes, {cle.cles_nulles} clé(s) nulle(s)")
    if cle.lignes != cle.cles_distinctes or cle.cles_nulles:
        raise SystemExit("Clé zone_id non unique ou nulle : la jointure multiplierait les trajets.")
    homonymes = zones.groupBy("zone").count().where("count > 1").orderBy("zone")
    print("Noms de zone partagés par plusieurs LocationID (=> ne jamais joindre sur le nom) :")
    homonymes.show(truncate=False)

    titre("5. Non-appariements (anti-jointure)")
    orphelins = valides.join(zones, valides.zone_depart == zones.zone_id, "left_anti")
    n_orphelins = orphelins.count()
    print(f"Trajets dont la zone de départ est absente de la table : {n_orphelins}")
    orphelins.groupBy("zone_depart").count().orderBy(F.desc("count")).show(10)
    non_localises = valides.where(F.col("zone_depart").isin(264, 265)).count()
    print(f"Trajets appariés à une zone non localisée (264 Unknown / 265 Outside of NYC) : {non_localises}")

    titre("6. Jointure et contrôle des volumes")
    enrichis = (valides.join(F.broadcast(zones), valides.zone_depart == zones.zone_id, "left")
                .drop("zone_id")
                .withColumn("arrondissement", F.coalesce("arrondissement", F.lit("Zone inconnue")))
                .cache())
    n_apres = enrichis.count()
    print(f"Avant jointure : {n_valides} · après jointure gauche : {n_apres} · non appariés : {n_orphelins}")
    assert n_apres == n_valides, "La jointure a multiplié des lignes"
    assert enrichis.select("ligne_source").distinct().count() == n_apres, "ligne_source dupliquée"
    print("OK : aucune multiplication (même effectif, ligne_source unique).")

    titre("7. Agrégations")
    total = F.sum("distance_miles")
    heures = F.sum("duree_s") / 3600.0
    par_arr = (enrichis.groupBy("arrondissement")
               .agg(F.count("*").alias("nb_trajets"),
                    F.round(total, 2).alias("distance_totale_miles"),
                    F.round(F.avg("distance_miles"), 3).alias("distance_moyenne_miles"),
                    F.round(F.percentile_approx("distance_miles", 0.5, 10000), 2).alias("distance_mediane_miles"),
                    F.round(F.avg("duree_s") / 60, 2).alias("duree_moyenne_min"),
                    F.round(total / heures, 2).alias("vitesse_ponderee_mph"))
               .withColumn("part_trajets_pct", F.round(100 * F.col("nb_trajets") / F.lit(n_apres), 3))
               .orderBy(F.desc("nb_trajets")))
    print("Plan d'exécution (agrégat par arrondissement) :")
    par_arr.explain(mode="formatted")
    par_zone = (enrichis.groupBy("zone_depart", "arrondissement", "zone")
                .agg(F.count("*").alias("nb_trajets"),
                     F.round(F.avg("distance_miles"), 3).alias("distance_moyenne_miles"),
                     F.round(F.avg("duree_s") / 60, 2).alias("duree_moyenne_min"),
                     F.round(total / heures, 2).alias("vitesse_ponderee_mph")))

    titre("8. Partitionnement")
    print("Partitions lecture JSONL :", brut.rdd.getNumPartitions())
    print("Partitions après jointure (broadcast, pas d'échange) :", enrichis.rdd.getNumPartitions())
    print("Partitions de l'agrégat (après échange + AQE) :", par_arr.rdd.getNumPartitions())

    titre("9. Export Parquet et relecture")
    sortie = str(args.sortie)
    par_arr.coalesce(1).write.mode("errorifexists").parquet(f"{sortie}/par_arrondissement")
    par_zone.coalesce(1).write.mode("errorifexists").parquet(f"{sortie}/par_zone")
    relu_arr = spark.read.parquet(f"{sortie}/par_arrondissement")
    relu_zone = spark.read.parquet(f"{sortie}/par_zone")
    relu_arr.printSchema()
    relu_arr.orderBy(F.desc("nb_trajets")).show(truncate=False)
    somme_arr = relu_arr.agg(F.sum("nb_trajets")).first()[0]
    somme_zone = relu_zone.agg(F.sum("nb_trajets")).first()[0]
    print(f"Relecture : somme nb_trajets par arrondissement = {somme_arr}, par zone = {somme_zone}, "
          f"attendu = {n_apres} ; zones distinctes = {relu_zone.count()}")
    assert somme_arr == somme_zone == n_apres, "Le Parquet relu ne restitue pas l'effectif joint"
    print("Top 5 zones de départ :")
    relu_zone.orderBy(F.desc("nb_trajets")).show(5, truncate=False)
    print(f"OK : Parquet écrit et relu dans {sortie}")


if __name__ == "__main__":
    main()
